"""Request/response models — the contract between engine and clients."""

from typing import Any

from pydantic import BaseModel


class RunRequest(BaseModel):
    """Incoming request body. The `data` dict provides values for
    the endpoint's prompt template placeholders."""

    data: dict[str, Any]


class RunResponseChunk(BaseModel):
    """A single SSE event in the response stream.

    Types:
        status              — processing update (e.g. "Agent 'coder_0' processing...")
        token               — final response content
        error               — something went wrong
        done                — stream is complete
        validation_rejected — pipeline output was rejected by the validator
    """

    type: str
    content: str
    agent: str | None = None
