"""LangGraph node functions — the async functions each graph node executes.

Each function calls an Anthropic LLM with a specific system prompt and
returns updated state. These are the building blocks the builder wires together.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from app.tools import resolve_tools

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.agents.registry import ResolvedAgent
    from app.agents.state import AgentState

logger = logging.getLogger(__name__)


def _extract_content(content) -> str:
    """Normalize message content — Anthropic can return a list of blocks or a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Extract text from content blocks: [{"type": "text", "text": "..."}]
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", str(block)))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


def _get_llm(model: str, tools: list | None = None) -> ChatAnthropic:
    """Create an Anthropic LLM instance, optionally with tool bindings."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
    llm = ChatAnthropic(model=model, max_tokens=4096, api_key=api_key)
    if tools:
        llm = llm.bind_tools(tools)
    return llm


async def _execute_tool_calls(tool_calls: list[dict], tools: list) -> list[ToolMessage]:
    """Execute tool calls from an LLM response and return ToolMessages."""
    tools_by_name = {t.name: t for t in tools}
    results: list[ToolMessage] = []
    for tc in tool_calls:
        tool = tools_by_name[tc["name"]]
        result = await tool.ainvoke(tc["args"])
        results.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    return results


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------


def make_agent_node(agent: ResolvedAgent) -> Callable:
    """Create a graph node that calls an LLM with the agent's system prompt.

    Used by single, sequential, orchestrator (all agents), and as the base
    for decentralised nodes.
    """
    tools = resolve_tools(agent.tools) if agent.tools else []

    async def agent_node(state: AgentState) -> dict:
        logger.info(f"Agent '{agent.name}' processing")
        try:
            llm = _get_llm(agent.model, tools=tools or None)
            messages = [SystemMessage(content=agent.prompt)] + list(state["messages"])

            while True:
                response = await llm.ainvoke(messages)
                if not getattr(response, "tool_calls", None):
                    break
                messages.append(response)
                tool_results = await _execute_tool_calls(response.tool_calls, tools)
                messages.extend(tool_results)

            # If the LLM ended with empty content after tool use, get a text response
            if tools and not _extract_content(response.content):
                logger.warning(f"Agent '{agent.name}' returned empty content after tool use — retrying for text")
                response = await _get_llm(agent.model).ainvoke(messages)

            return {
                "messages": [response],
                "current_agent": agent.name,
                "final_response": _extract_content(response.content),
            }
        except Exception as e:
            logger.error(f"Agent '{agent.name}' error: {e}", exc_info=True)
            error_msg = AIMessage(content=f"Error in agent '{agent.name}': {e}")
            return {
                "messages": [error_msg],
                "current_agent": agent.name,
                "final_response": str(e),
            }

    agent_node.__name__ = agent.name
    return agent_node


def make_validator_node(agent: ResolvedAgent) -> Callable:
    """Create a validator node.

    Like make_agent_node but after the tool-call loop, inspects tool results
    for __ACCEPTED__ / __REJECTED__ sentinels. Sets validation_result and
    increments retry_count in returned state. If the LLM calls no tool,
    treats as implicit accept (logs warning).
    """
    tools = resolve_tools(agent.tools) if agent.tools else []

    async def validator_node(state: AgentState) -> dict:
        logger.info(f"Validator '{agent.name}' processing")
        try:
            llm = _get_llm(agent.model, tools=tools or None)
            messages = [SystemMessage(content=agent.prompt)] + list(state["messages"])

            tool_results: list[ToolMessage] = []

            while True:
                response = await llm.ainvoke(messages)
                if not getattr(response, "tool_calls", None):
                    break
                messages.append(response)
                batch = await _execute_tool_calls(response.tool_calls, tools)
                tool_results.extend(batch)
                messages.extend(batch)

            # If the LLM ended with empty content after tool use, get a text response
            if tools and not _extract_content(response.content):
                logger.warning(f"Validator '{agent.name}' returned empty content after tool use — retrying for text")
                response = await _get_llm(agent.model).ainvoke(messages)

            # Inspect tool results for sentinel values
            validation_result: str | None = None
            for tr in tool_results:
                content = tr.content if isinstance(tr.content, str) else str(tr.content)
                if "__ACCEPTED__" in content:
                    validation_result = "accepted"
                    break
                if "__REJECTED__:" in content:
                    validation_result = "rejected"
                    break

            if validation_result is None:
                # No tool called — implicit accept
                logger.warning(
                    f"Validator '{agent.name}' called no tool — treating as implicit accept"
                )
                validation_result = "accepted"

            retry_count = state.get("retry_count", 0)
            if validation_result == "rejected":
                retry_count += 1

            return {
                "messages": [response],
                "current_agent": agent.name,
                "final_response": _extract_content(response.content),
                "validation_result": validation_result,
                "retry_count": retry_count,
            }
        except Exception as e:
            logger.error(f"Validator '{agent.name}' error: {e}", exc_info=True)
            error_msg = AIMessage(content=f"Error in validator '{agent.name}': {e}")
            return {
                "messages": [error_msg],
                "current_agent": agent.name,
                "final_response": str(e),
                "validation_result": "rejected",
                "retry_count": state.get("retry_count", 0) + 1,
            }

    validator_node.__name__ = agent.name
    return validator_node


def make_decentralised_node(
    agent: ResolvedAgent, all_agents: list[ResolvedAgent]
) -> Callable:
    """Create a node for decentralised topology.

    Like a regular agent node, but the system prompt is extended with
    delegation instructions. The agent can hand off work to peers.
    """
    other_agents = [a for a in all_agents if a.name != agent.name]
    agent_descriptions = "\n".join(
        f"- **{a.name}**: {a.description}" for a in other_agents
    )

    extended_prompt = f"""{agent.prompt}

## Delegation
You can delegate to other agents if the request is outside your expertise.
To delegate, respond ONLY with JSON:
{{"delegate": "agent_name", "message": "what you need them to do"}}

Available agents:
{agent_descriptions}

If you can handle the request yourself, respond normally (no JSON).
Only delegate if the task genuinely requires another agent's expertise."""

    tools = resolve_tools(agent.tools) if agent.tools else []

    async def decentralised_node(state: AgentState) -> dict:
        logger.info(f"Agent '{agent.name}' processing (decentralised)")
        try:
            llm = _get_llm(agent.model, tools=tools or None)
            messages = [SystemMessage(content=extended_prompt)] + list(state["messages"])

            while True:
                response = await llm.ainvoke(messages)
                if not getattr(response, "tool_calls", None):
                    break
                messages.append(response)
                tool_results = await _execute_tool_calls(response.tool_calls, tools)
                messages.extend(tool_results)

            # If the LLM ended with empty content after tool use, get a text response
            if tools and not _extract_content(response.content):
                logger.warning(f"Agent '{agent.name}' returned empty content after tool use — retrying for text")
                response = await _get_llm(agent.model).ainvoke(messages)

            return {
                "messages": [response],
                "current_agent": agent.name,
                "final_response": _extract_content(response.content),
            }
        except Exception as e:
            logger.error(f"Agent '{agent.name}' error: {e}", exc_info=True)
            error_msg = AIMessage(content=f"Error in agent '{agent.name}': {e}")
            return {
                "messages": [error_msg],
                "current_agent": agent.name,
                "final_response": str(e),
            }

    decentralised_node.__name__ = agent.name
    return decentralised_node


# ---------------------------------------------------------------------------
# Routing functions — parse LLM output to decide next node
# ---------------------------------------------------------------------------


def route_decision(state: AgentState, agent_names: list[str]) -> str:
    """Parse the orchestrator's output to decide which agent to call next.

    Looks for: {"agent": "agent_name"} or {"agent": "__done__", "response": "..."}
    Falls back to checking if any agent name appears in the text.
    """
    last_message = state["messages"][-1]
    raw = last_message.content if hasattr(last_message, "content") else ""
    content = _extract_content(raw)

    # Try JSON parse
    try:
        data = json.loads(content.strip())
        target = data.get("agent", "")

        if target == "__done__":
            response = data.get("response", "")
            if response:
                state["final_response"] = response
            return "__done__"

        if target in agent_names:
            return target
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: check if any agent name appears in the text
    content_lower = content.lower()
    for name in agent_names:
        if name.lower() in content_lower:
            logger.info(f"Fallback routing: found '{name}' in orchestrator output")
            return name

    # Default: done
    logger.warning("Could not parse routing decision, defaulting to __done__")
    return "__done__"


def route_delegation(state: AgentState, agent_names: list[str]) -> str:
    """Parse a decentralised agent's output for delegation.

    Looks for: {"delegate": "agent_name", "message": "..."}
    If no delegation JSON found, the agent is responding directly → done.
    """
    last_message = state["messages"][-1]
    raw = last_message.content if hasattr(last_message, "content") else ""
    content = _extract_content(raw)

    try:
        data = json.loads(content.strip())
        target = data.get("delegate", "")
        if target in agent_names:
            logger.info(f"Delegation: → {target}")
            return target
    except (json.JSONDecodeError, AttributeError):
        pass

    # No delegation JSON → agent is giving a final answer
    return "__done__"


def route_validation(state: AgentState, first_agent_name: str) -> str:
    """Route after the validator node.

    Returns:
        first_agent_name  — retry the pipeline (up to MAX_RETRIES)
        "__accepted__"    — validation passed, forward output
        "__error__"       — too many rejections
    """
    from app.agents.builder import MAX_RETRIES

    validation_result = state.get("validation_result")
    retry_count = state.get("retry_count", 0)

    if validation_result == "accepted":
        return "__accepted__"

    if retry_count >= MAX_RETRIES:
        logger.warning(
            f"Pipeline rejected {retry_count} times — giving up"
        )
        return "__error__"

    logger.info(
        f"Pipeline rejected, retrying (attempt {retry_count}/{MAX_RETRIES})"
    )
    return first_agent_name
