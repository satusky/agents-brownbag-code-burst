"""Checkpointers for graphs that pause (interrupt) or need durable state.

LangGraph 1.2 warns when a checkpoint restores a Pydantic model it was not told
about, and plans to block it. ``make_checkpointer()`` allowlists the Pydantic
models defined in *this project's* code (not third-party libraries), so state
like ``OpportunityFacts`` round-trips quietly. Call it after your state models
are defined (e.g. at the bottom of a graph module).
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

_THIRD_PARTY = ("pydantic", "langchain", "langgraph", "langsmith", "openai", "fastapi", "starlette", "httpx")


def project_models() -> list[type[BaseModel]]:
    """Every Pydantic model class defined outside the third-party libraries above."""
    found, stack = [], list(BaseModel.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if not cls.__module__.split(".")[0].startswith(_THIRD_PARTY) and "[" not in cls.__name__:
            found.append(cls)
    return found


def make_checkpointer(*extra: type) -> InMemorySaver:
    """An in-memory checkpointer that may restore this project's Pydantic state types."""
    serde = JsonPlusSerializer(allowed_msgpack_modules=[*project_models(), *extra])
    return InMemorySaver(serde=serde)
