"""Graph cache — one compiled graph per system.

Since each system defines its own topology and agents,
the cache is keyed by system_id.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from app.agents.builder import build_graph

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from app.agents.registry import ResolvedAgent
    from app.config import SystemConfig

logger = logging.getLogger(__name__)

# Cache: {system_id: (config_hash, compiled_graph)}
_cache: dict[str, tuple[str, CompiledStateGraph]] = {}


def _hash_system(system: SystemConfig, agents: list[ResolvedAgent]) -> str:
    """Hash the system config + its resolved agents for change detection."""
    data = {
        "system": system.model_dump(),
        "agents": [
            {
                "name": a.name,
                "type": a.type,
                "description": a.description,
                "model": a.model,
                "tools": a.tools,
                "prompt": a.prompt,
            }
            for a in agents
        ],
    }
    config_json = json.dumps(data, sort_keys=True)
    return hashlib.sha256(config_json.encode()).hexdigest()[:16]


def get_or_build(
    system: SystemConfig, agents: list[ResolvedAgent]
) -> CompiledStateGraph:
    """Return cached graph for this system, or build a new one."""
    config_hash = _hash_system(system, agents)

    if system.id in _cache:
        cached_hash, cached_graph = _cache[system.id]
        if cached_hash == config_hash:
            logger.debug(f"Graph cache hit: {system.id}")
            return cached_graph

    logger.info(
        f"Building graph for system '{system.id}' "
        f"(topology={system.topology}, agents={len(agents)})"
    )
    graph = build_graph(system, agents)
    _cache[system.id] = (config_hash, graph)
    return graph


def invalidate(system_id: str | None = None) -> None:
    """Clear the cache. If system_id given, only clear that system."""
    global _cache
    if system_id:
        _cache.pop(system_id, None)
        logger.info(f"Graph cache invalidated: {system_id}")
    else:
        _cache.clear()
        logger.info("Graph cache invalidated: all systems")
