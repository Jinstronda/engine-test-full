"""LangGraph shared state — flows between nodes during graph execution."""

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """State passed through every node in the graph.

    messages           — conversation history; add_messages reducer appends
                         new messages rather than overwriting.
    current_agent      — name of the agent currently processing.
    final_response     — the answer to return to the client.
    retry_count        — number of times the pipeline has been rejected by validator.
    validation_result  — "accepted" | "rejected" | None
    """

    messages: Annotated[list[BaseMessage], add_messages]
    current_agent: str | None
    final_response: str | None
    retry_count: int
    validation_result: str | None
