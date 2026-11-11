"""Evaluator-optimizer: one model writes, another grades, until the draft passes.

write (model) → evaluate (model) ⇄ write
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from agents_brownbag_code_burst.models import get_model

llm = get_model()


class Grade(BaseModel):
    passed: bool
    feedback: str


grader = llm.with_structured_output(Grade)


class State(TypedDict):
    announcement: str
    draft: str
    passed: bool
    feedback: str
    tries: int


def write(state: State) -> dict:
    prompt = f"Write a short funding recommendation from:\n{state['announcement']}"
    if state.get("feedback"):  # a second try: fix what the grader found
        prompt += f"\n\nYour last draft:\n{state['draft']}\n\nFix:\n{state['feedback']}"
    return {"draft": llm.invoke(prompt).text, "tries": state.get("tries", 0) + 1}


def evaluate(state: State) -> dict:
    grade = grader.invoke(
        "Grade the draft against the announcement. Fail it if any date "
        "has the wrong type (letter of intent vs. full proposal).\n\n"
        f"ANNOUNCEMENT:\n{state['announcement']}\n\nDRAFT:\n{state['draft']}"
    )
    return {"passed": grade.passed, "feedback": grade.feedback}


def next_step(state: State) -> str:
    if state["passed"] or state["tries"] >= 3:  # code decides when to stop
        return END
    return "write"


builder = StateGraph(State)
builder.add_node("write", write)
builder.add_node("evaluate", evaluate)
builder.add_edge(START, "write")
builder.add_edge("write", "evaluate")
builder.add_conditional_edges("evaluate", next_step, ["write", END])  # the loop
graph = builder.compile()


if __name__ == "__main__":
    announcement = (
        "DEMO-101 Climate Data Cyberinfrastructure. Universities may apply. "
        "Letter of intent due 2026-12-01; full proposal due 2027-02-15."
    )
    result = graph.invoke({"announcement": announcement})
    print(f"Passed: {result['passed']} after {result['tries']} tries\n")
    print(result["draft"])
