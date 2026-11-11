"""Human in the loop: the same loop, but a person is the evaluator.

write (model) → review (pauses for a person) ⇄ write
"""

from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agents_brownbag_code_burst.models import get_model

llm = get_model()


class State(TypedDict):
    announcement: str
    draft: str
    feedback: str


def write(state: State) -> dict:
    prompt = f"Write a short funding recommendation from:\n{state['announcement']}"
    if state.get("feedback"):
        prompt += f"\n\nYour last draft:\n{state['draft']}\n\nFix:\n{state['feedback']}"
    return {"draft": llm.invoke(prompt).text}


def review(state: State) -> dict:
    feedback = interrupt(state["draft"])  # pause here until a person answers
    return {"feedback": feedback}


def next_step(state: State) -> str:
    return END if state["feedback"].lower() == "approve" else "write"


builder = StateGraph(State)
builder.add_node("write", write)
builder.add_node("review", review)
builder.add_edge(START, "write")
builder.add_edge("write", "review")
builder.add_conditional_edges("review", next_step, ["write", END])
graph = builder.compile(checkpointer=InMemorySaver())  # pausing needs a checkpointer


if __name__ == "__main__":
    config = {"configurable": {"thread_id": "demo"}}  # which saved run to resume
    announcement = (
        "DEMO-101 Climate Data Cyberinfrastructure. Universities may apply. "
        "Letter of intent due 2026-12-01; full proposal due 2027-02-15."
    )
    result = graph.invoke({"announcement": announcement}, config)
    while "__interrupt__" in result:  # paused: show the draft and ask a person
        print("\n" + result["__interrupt__"][0].value)
        answer = input("\nType 'approve', or say what to fix: ").strip()
        result = graph.invoke(Command(resume=answer), config)  # pick up where it paused
    print("\nApproved.")
