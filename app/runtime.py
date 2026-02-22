"""Runtime — bridges HTTP requests to LangGraph execution.

Validates contracts, renders prompt templates, runs the graph, and yields SSE events.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

from langchain_core.messages import HumanMessage

from app.agents import cache as graph_cache
from app.agents.nodes import _extract_content
from app.agents.registry import merge_agent
from app.config import ContractField, EngineConfig, SystemConfig
from app.schemas import RunResponseChunk

logger = logging.getLogger(__name__)


def validate_contract(contract: list[ContractField], data: dict) -> None:
    """Check that all contract fields are present in data with correct types.

    Raises ValueError with a descriptive message on failure.
    """
    type_map = {
        "string": str,
        "number": (int, float),
        "boolean": bool,
    }

    for field in contract:
        if field.name not in data:
            raise ValueError(
                f"Missing required field '{field.name}' (expected type: {field.type})"
            )

        value = data[field.name]
        expected = type_map[field.type]

        # bool is a subclass of int in Python, so check bool explicitly for "number"
        if field.type == "number" and isinstance(value, bool):
            raise ValueError(
                f"Field '{field.name}' must be a number, got boolean"
            )

        if not isinstance(value, expected):
            actual_type = type(value).__name__
            raise ValueError(
                f"Field '{field.name}' must be of type {field.type}, "
                f"got {actual_type}"
            )


def render_prompt(template: str, data: dict) -> str:
    """Fill placeholders in the prompt template with data values.

    Template: "Analyze: {user_input}"
    Data:     {"user_input": "Python vs Rust"}
    Result:   "Analyze: Python vs Rust"
    """
    try:
        return template.format_map(data)
    except KeyError as e:
        logger.warning(f"Template key error: {e}, appending raw data")
        data_str = json.dumps(data, indent=2, default=str)
        return f"{template}\n\nData:\n{data_str}"


async def execute_run(
    config: EngineConfig,
    system: SystemConfig,
    prompt: str,
) -> AsyncGenerator[RunResponseChunk, None]:
    """Execute the agent graph and yield SSE response chunks.

    1. Resolve agents from the system config
    2. Get or build graph from cache
    3. Stream graph execution
    4. Yield status/token/validation_rejected/error/done events
    """
    logger.info(
        f"Executing run: system={system.id}, topology={system.topology}"
    )

    # 1. Resolve agents
    try:
        agents = [merge_agent(ref, i) for i, ref in enumerate(system.agents)]
        graph = graph_cache.get_or_build(system, agents)
    except Exception as e:
        logger.error(f"Failed to build graph: {e}")
        yield RunResponseChunk(type="error", content=f"Graph build error: {e}")
        yield RunResponseChunk(type="done", content="")
        return

    # 2. Execute
    yield RunResponseChunk(type="status", content="Processing request...")

    initial_state = {
        "messages": [HumanMessage(content=prompt)],
        "current_agent": None,
        "final_response": None,
        "retry_count": 0,
        "validation_result": None,
    }

    try:
        last_agent = None
        final_content = None

        async for event in graph.astream(initial_state):
            for node_name, state_update in event.items():
                if node_name == "__end__":
                    continue

                # Track agent switches for status updates
                current = state_update.get("current_agent", node_name)
                if current != last_agent:
                    yield RunResponseChunk(
                        type="status",
                        content=f"Agent '{current}' processing...",
                        agent=current,
                    )
                    last_agent = current

                # Emit validation_rejected event when pipeline is rejected
                if state_update.get("validation_result") == "rejected":
                    yield RunResponseChunk(
                        type="validation_rejected",
                        content="Pipeline output rejected, retrying...",
                        agent=current,
                    )

                # Capture response content — skip routing/delegation JSON
                messages = state_update.get("messages", [])
                for msg in messages:
                    raw = msg.content if hasattr(msg, "content") else str(msg)
                    content = _extract_content(raw)
                    if not content:
                        continue
                    try:
                        parsed = json.loads(content.strip())
                        if parsed.get("agent") == "__done__" and parsed.get("response"):
                            # Extract the embedded final answer from __done__ JSON
                            final_content = parsed["response"]
                        elif "agent" in parsed or "delegate" in parsed:
                            pass  # routing JSON — skip
                        else:
                            final_content = content
                    except (json.JSONDecodeError, TypeError):
                        final_content = content

                # Also check the explicit final_response field
                if state_update.get("final_response"):
                    fr = state_update["final_response"]
                    try:
                        parsed = json.loads(fr)
                        if parsed.get("agent") == "__done__" and parsed.get("response"):
                            final_content = parsed["response"]
                        elif "agent" in parsed or "delegate" in parsed:
                            continue
                    except (json.JSONDecodeError, TypeError):
                        final_content = fr

        # 3. Yield final response
        if final_content:
            yield RunResponseChunk(
                type="token",
                content=final_content,
                agent=last_agent,
            )

    except Exception as e:
        logger.error(f"Graph execution error: {e}", exc_info=True)
        yield RunResponseChunk(type="error", content=f"Execution error: {e}")

    yield RunResponseChunk(type="done", content="")
