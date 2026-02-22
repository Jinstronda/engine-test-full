"""Engine-2 — FastAPI app with three-level hierarchy config.

Loads config.yaml on startup. Exposes /run/{slug} for SSE streaming,
plus operational endpoints for health, config viewing, and hot-reload.
Scheduler runs async functions on cron schedules.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agents.cache import invalidate as invalidate_cache
from app.config import get_config, load_config, reload_config
from app.runtime import execute_run, render_prompt, validate_contract
from app.scheduler import setup_scheduler
from app.schemas import RunRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load config and start scheduler on startup."""
    config = load_config()
    scheduler = setup_scheduler(config)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        f"Engine-2 started (origins={config.allowed_origins}, "
        f"auth={'enabled' if config.api_key else 'disabled'}, "
        f"systems={len(config.systems)}, endpoints={len(config.endpoints)}, "
        f"async_functions={len(config.async_functions)})"
    )
    yield
    scheduler.shutdown()
    logger.info("Engine-2 shutting down")


# Load config early so we can read allowed_origins for CORS middleware.
_boot_config = load_config()

app = FastAPI(title="Fabriq Engine-2", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_boot_config.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def verify_api_key(request: Request) -> None:
    """Validate X-API-Key header against the configured key.
    If no api_key is set in config, auth is disabled (dev mode).
    """
    config = get_config()
    if not config.api_key:
        return  # Auth disabled — no key configured

    key = request.headers.get("X-API-Key")
    if key != config.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# Runtime endpoint
# ---------------------------------------------------------------------------


@app.post("/run/{endpoint_slug}", dependencies=[Depends(verify_api_key)])
async def run_endpoint(endpoint_slug: str, request: RunRequest):
    """Execute the agent pipeline for a specific endpoint.

    Streams response as Server-Sent Events (SSE).
    """
    config = get_config()

    endpoint = config.get_endpoint(endpoint_slug)
    if not endpoint:
        raise HTTPException(
            status_code=404,
            detail=f"Endpoint '{endpoint_slug}' not found",
        )

    try:
        validate_contract(endpoint.contract, request.data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    prompt = render_prompt(endpoint.prompt, request.data)
    system = config.get_system(endpoint.system_id)

    async def stream():
        async for chunk in execute_run(config, system, prompt):
            data = json.dumps(chunk.model_dump())
            yield f"data: {data}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Operational endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Liveness check."""
    config = get_config()
    return {
        "status": "healthy",
        "systems": len(config.systems),
        "endpoints": len(config.endpoints),
    }


@app.get("/config")
async def get_current_config():
    """Return current config as JSON."""
    config = get_config()
    return config.model_dump()


@app.post("/reload", dependencies=[Depends(verify_api_key)])
async def reload(request: Request):
    """Hot-reload config.yaml without container restart.

    Stops the current scheduler, reloads config, invalidates graph cache,
    and starts a new scheduler.
    """
    try:
        new_config = reload_config()
        invalidate_cache()

        request.app.state.scheduler.shutdown(wait=False)
        new_scheduler = setup_scheduler(new_config)
        new_scheduler.start()
        request.app.state.scheduler = new_scheduler

        return {
            "status": "reloaded",
            "systems": len(new_config.systems),
            "endpoints": len(new_config.endpoints),
        }
    except Exception as e:
        logger.error(f"Reload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Reload failed: {e}")
