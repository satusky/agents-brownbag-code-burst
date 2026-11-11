"""Human approval as a graph step, built on LangGraph's ``interrupt()``.

The contract used everywhere in this repo (CLI, web viewer, Studio):

* the graph pauses with a payload: ``{"ask": "...", <item fields>}``
* a person resumes it with ``Command(resume={"approved": bool, "feedback": [str, ...]})``

``request_approval`` also accepts a bare ``True``/``False`` or a string, so
quick experiments in Studio still work. The compiled graph needs a checkpointer.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt
from pydantic import BaseModel

_YES = {"y", "yes", "approve", "approved", "ok", "lgtm"}


class Approval(BaseModel):
    approved: bool
    feedback: list[str] = []


def normalize_answer(answer: Any) -> Approval:
    if isinstance(answer, Approval):
        return answer
    if isinstance(answer, bool):
        return Approval(approved=answer)
    if isinstance(answer, str):
        text = answer.strip()
        return Approval(approved=True) if text.lower() in _YES else Approval(approved=False, feedback=[text])
    if isinstance(answer, dict):
        feedback = answer.get("feedback") or []
        return Approval(approved=bool(answer.get("approved")), feedback=[feedback] if isinstance(feedback, str) else feedback)
    raise TypeError(f"Cannot interpret approval answer {answer!r}")


def request_approval(item: dict, ask: str = "Approve, or list fixes") -> Approval:
    """Pause the run until a person approves or returns feedback."""
    return normalize_answer(interrupt({"ask": ask, **item}))
