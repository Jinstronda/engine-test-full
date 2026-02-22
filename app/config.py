"""Configuration loader — reads config.yaml, validates with Pydantic.

Three-level hierarchy: endpoints → systems → agent instances.
Agent types (model/tools) are hardcoded in agents/registry.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

logger = logging.getLogger(__name__)


class ContractField(BaseModel):
    """A typed field in an endpoint's input contract."""

    name: str
    type: Literal["string", "number", "boolean"]


class EndpointConfig(BaseModel):
    """One callable endpoint — references a system and defines its contract."""

    slug: str
    description: str | None = None
    system_id: str
    contract: list[ContractField] = []
    prompt: str  # template with {placeholders}


class SystemAgentRef(BaseModel):
    """A reference to an agent type within a system, with an instance prompt."""

    type: str   # must exist in AGENT_TYPE_REGISTRY
    prompt: str


class SystemConfig(BaseModel):
    """A reusable agent system with a fixed topology."""

    id: str
    name: str
    description: str | None = None
    topology: Literal["single", "sequential", "orchestrator", "decentralised"]
    agents: list[SystemAgentRef]

    @field_validator("agents")
    @classmethod
    def must_have_agents(cls, v: list[SystemAgentRef]) -> list[SystemAgentRef]:
        if not v:
            raise ValueError("A system must have at least one agent")
        return v


class ScheduleConfig(BaseModel):
    """Cron-style schedule for async functions."""

    frequency: Literal["daily", "weekly", "monthly"]
    hour: int                      # 0-23
    day_of_week: str | None = None  # required for weekly (e.g. "mon", "0")
    day_of_month: int | None = None # required for monthly (1-31)

    @model_validator(mode="after")
    def validate_schedule_fields(self) -> ScheduleConfig:
        if self.frequency == "weekly" and self.day_of_week is None:
            raise ValueError("day_of_week is required for weekly schedules")
        if self.frequency == "monthly" and self.day_of_month is None:
            raise ValueError("day_of_month is required for monthly schedules")
        return self


class AsyncFunctionConfig(BaseModel):
    """A scheduled async function that runs a system on a cron schedule."""

    system_id: str
    prompt: str
    schedule: ScheduleConfig


class EngineConfig(BaseModel):
    """Top-level engine configuration."""

    endpoints: list[EndpointConfig]
    systems: list[SystemConfig]
    async_functions: list[AsyncFunctionConfig] = []

    # Auth & CORS
    api_key: str | None = None
    allowed_origins: list[str] = ["*"]

    @model_validator(mode="after")
    def validate_references(self) -> EngineConfig:
        from app.agents.registry import AGENT_TYPE_REGISTRY

        system_ids = {s.id for s in self.systems}

        # Validate endpoint → system references
        for ep in self.endpoints:
            if ep.system_id not in system_ids:
                raise ValueError(
                    f"Endpoint '{ep.slug}' references unknown system_id '{ep.system_id}'. "
                    f"Available: {sorted(system_ids)}"
                )

        # Validate async_function → system references
        for fn in self.async_functions:
            if fn.system_id not in system_ids:
                raise ValueError(
                    f"async_function references unknown system_id '{fn.system_id}'. "
                    f"Available: {sorted(system_ids)}"
                )

        # Validate agent type references within systems
        for system in self.systems:
            for ref in system.agents:
                if ref.type not in AGENT_TYPE_REGISTRY:
                    raise ValueError(
                        f"System '{system.id}' references unknown agent type '{ref.type}'. "
                        f"Available: {sorted(AGENT_TYPE_REGISTRY.keys())}"
                    )

        return self

    def get_system(self, system_id: str) -> SystemConfig:
        """Return a system by ID. Raises ValueError if not found."""
        for system in self.systems:
            if system.id == system_id:
                return system
        raise ValueError(
            f"System '{system_id}' not found. "
            f"Available: {[s.id for s in self.systems]}"
        )

    def get_endpoint(self, slug: str) -> EndpointConfig | None:
        """Return an endpoint by slug, or None if not found."""
        for ep in self.endpoints:
            if ep.slug == slug:
                return ep
        return None


# ---------------------------------------------------------------------------
# Module-level config cache
# ---------------------------------------------------------------------------

_config: EngineConfig | None = None
_config_path: str = "config.yaml"


def load_config(path: str = "config.yaml") -> EngineConfig:
    """Read config.yaml from disk, validate, and cache."""
    global _config, _config_path
    _config_path = path

    config_file = Path(path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file.resolve()}")

    raw = yaml.safe_load(config_file.read_text())
    _config = EngineConfig(**raw)

    logger.info(
        f"Loaded config: "
        f"systems={len(_config.systems)}, endpoints={len(_config.endpoints)}"
    )
    return _config


def get_config() -> EngineConfig:
    """Return cached config. Raises if not yet loaded."""
    if _config is None:
        raise RuntimeError("Config not loaded — call load_config() first")
    return _config


def reload_config() -> EngineConfig:
    """Re-read config from disk. Called by /reload endpoint."""
    logger.info(f"Reloading config from {_config_path}")
    return load_config(_config_path)
