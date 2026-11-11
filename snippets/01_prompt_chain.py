"""Prompt chaining: each step's output is the next step's input.

extract (model) → write_brief (model)
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agents_brownbag_code_burst.models import get_model

llm = get_model()


class State(TypedDict):
    announcement: str
    facts: str
    brief: str


def extract(state: State) -> dict:
    reply = llm.invoke(f"List the key facts:\n{state['announcement']}")
    return {"facts": reply.text}


def write_brief(state: State) -> dict:
    reply = llm.invoke(f"Write a two-sentence brief for researchers:\n{state['facts']}")
    return {"brief": reply.text}


builder = StateGraph(State)
builder.add_node("extract", extract)
builder.add_node("write_brief", write_brief)
builder.add_edge(START, "extract")
builder.add_edge("extract", "write_brief")  # one fixed path
builder.add_edge("write_brief", END)
graph = builder.compile()


if __name__ == "__main__":
    announcement = (
        "DEMO-101 Climate Data Cyberinfrastructure. Funds shared platforms "
        "and computing services for climate research. Universities may apply. "
        "Letter of intent due 2026-12-01; full proposal due 2027-02-15."
    )
    result = graph.invoke({"announcement": announcement})
    print(result["brief"])
