"""Graph builder — wires agent nodes into a LangGraph StateGraph.

Takes a system's topology and resolved agents and constructs one of
four graph types:
- single:         one agent, one step
- sequential:     agents run in order, with validator/retry loop
- orchestrator:   first agent routes to specialists
- decentralised:  agents delegate to each other peer-to-peer
"""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from app.agents.nodes import (
    make_agent_node,
    make_decentralised_node,
    make_validator_node,
    route_decision,
    route_delegation,
    route_validation,
)
from app.agents.state import AgentState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from app.agents.registry import ResolvedAgent
    from app.config import SystemConfig

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
MAX_ITERATIONS = 5  # Guard against infinite loops in orchestrator/decentralised


def build_graph(
    system: SystemConfig, agents: list[ResolvedAgent]
) -> CompiledStateGraph:
    """Build and compile a LangGraph for a specific system."""
    match system.topology:
        case "single":
            return _build_single(agents[0])
        case "sequential":
            return _build_sequential(agents)
        case "orchestrator":
            return _build_orchestrator(system, agents)
        case "decentralised":
            return _build_decentralised(agents)
        case _:
            raise ValueError(f"Unknown topology: {system.topology}")


# ---------------------------------------------------------------------------
# Topology builders
# ---------------------------------------------------------------------------


def _build_single(agent: ResolvedAgent) -> CompiledStateGraph:
    """Single agent → END.

    START → [agent] → END
    """
    graph = StateGraph(AgentState)

    graph.add_node(agent.name, make_agent_node(agent))
    graph.set_entry_point(agent.name)
    graph.add_edge(agent.name, END)

    logger.info(f"Built single graph: {agent.name}")
    return graph.compile()


def _build_sequential(agents: list[ResolvedAgent]) -> CompiledStateGraph:
    """Agents run in order with a validator/retry loop on the last agent.

    START → [agents[0]] → [agents[1]] → ... → [validator] → conditional
      conditional: route_validation(state, agents[0].name)
        → agents[0].name  (retry, up to MAX_RETRIES times)
        → "__accepted__"  → END
        → "__error__"     → END
    """
    if len(agents) < 2:
        return _build_single(agents[0])

    graph = StateGraph(AgentState)

    # All agents except last use make_agent_node; last uses make_validator_node
    for agent in agents[:-1]:
        graph.add_node(agent.name, make_agent_node(agent))

    validator = agents[-1]
    graph.add_node(validator.name, make_validator_node(validator))

    # Entry point
    graph.set_entry_point(agents[0].name)

    # Wire intermediate agents in sequence
    for i in range(len(agents) - 2):
        graph.add_edge(agents[i].name, agents[i + 1].name)

    # Last non-validator agent → validator
    graph.add_edge(agents[-2].name, validator.name)

    # Validator → conditional routing
    first_agent_name = agents[0].name
    destinations = {
        first_agent_name: first_agent_name,
        "__accepted__": END,
        "__error__": END,
    }

    graph.add_conditional_edges(
        validator.name,
        partial(route_validation, first_agent_name=first_agent_name),
        destinations,
    )

    logger.info(
        f"Built sequential graph: {' → '.join(a.name for a in agents)} (with validator retry)"
    )
    return graph.compile()


def _build_orchestrator(
    system: SystemConfig, agents: list[ResolvedAgent]
) -> CompiledStateGraph:
    """First agent is the orchestrator; routes to specialists in a loop.

    START → [agents[0]] → conditional (route_decision)
      → agents[1].name → [agents[0]]
      → agents[2].name → [agents[0]]
      → "__done__"     → END

    All agents (including agents[0]) built with make_agent_node.
    """
    graph = StateGraph(AgentState)
    agent_names = [a.name for a in agents]

    # Add all agents as regular nodes
    for agent in agents:
        graph.add_node(agent.name, make_agent_node(agent))

    # Entry: start with the first agent (orchestrator)
    graph.set_entry_point(agents[0].name)

    # Orchestrator can route to any of the specialist agents (not itself)
    specialist_names = [a.name for a in agents[1:]]
    destinations = {name: name for name in specialist_names}
    destinations["__done__"] = END

    graph.add_conditional_edges(
        agents[0].name,
        partial(route_decision, agent_names=specialist_names),
        destinations,
    )

    # Each specialist → back to orchestrator (agents[0])
    for agent in agents[1:]:
        graph.add_edge(agent.name, agents[0].name)

    logger.info(
        f"Built orchestrator graph: entry={agents[0].name}, "
        f"specialists={specialist_names}"
    )
    return graph.compile()


def _build_decentralised(agents: list[ResolvedAgent]) -> CompiledStateGraph:
    """Peer-to-peer agent delegation.

    START → [agent_0] → conditional → [agent_x] → conditional → ... → END

    Any agent can delegate to any other. First agent is the entry point.
    """
    graph = StateGraph(AgentState)
    agent_names = [a.name for a in agents]

    # Add all agent nodes with delegation capabilities
    for agent in agents:
        graph.add_node(agent.name, make_decentralised_node(agent, agents))

    # Entry: first agent
    graph.set_entry_point(agents[0].name)

    # Each agent → conditional: delegate to another or done
    destinations = {name: name for name in agent_names}
    destinations["__done__"] = END

    for agent in agents:
        graph.add_conditional_edges(
            agent.name,
            partial(route_delegation, agent_names=agent_names),
            destinations,
        )

    logger.info(f"Built decentralised graph: agents={agent_names}")
    return graph.compile()
