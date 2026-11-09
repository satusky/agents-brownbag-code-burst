"""Subgraphs + supervisor: a compiled graph can be a node; code picks which runs next.

supervisor (code) → discover (subgraph) | assess (subgraph) → supervisor
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from brown_bag_demos.models import get_model

llm = get_model()


class State(TypedDict):
    request: str
    opportunities: str
    ranking: str
    assessment: str
    next: str


# ---------------------------------------------- subgraph 1: discover (one step)
def search(state: State) -> dict:
    reply = llm.invoke(f"List three types of grants for: {state['request']}")
    return {"opportunities": reply.text}


discover_builder = StateGraph(State)
discover_builder.add_node("search", search)
discover_builder.add_edge(START, "search")
discover_builder.add_edge("search", END)
discover = discover_builder.compile()


# ---------------------------------------------- subgraph 2: assess (two steps)
def rank(state: State) -> dict:
    reply = llm.invoke(f"Rank by fit for {state['request']}:\n{state['opportunities']}")
    return {"ranking": reply.text}


def recommend(state: State) -> dict:
    reply = llm.invoke(f"In two sentences, recommend the top one:\n{state['ranking']}")
    return {"assessment": reply.text}


assess_builder = StateGraph(State)
assess_builder.add_node("rank", rank)
assess_builder.add_node("recommend", recommend)
assess_builder.add_edge(START, "rank")
assess_builder.add_edge("rank", "recommend")
assess_builder.add_edge("recommend", END)
assess = assess_builder.compile()


# ---------------------------------------------- parent graph: the supervisor
def supervisor(state: State) -> dict:  # plain code decides what runs next
    if not state.get("opportunities"):
        return {"next": "discover"}
    if not state.get("assessment"):
        return {"next": "assess"}
    return {"next": END}


builder = StateGraph(State)
builder.add_node("supervisor", supervisor)
builder.add_node("discover", discover)  # a compiled graph is a node
builder.add_node("assess", assess)
builder.add_edge(START, "supervisor")
builder.add_conditional_edges("supervisor", lambda s: s["next"],
                              ["discover", "assess", END])
builder.add_edge("discover", "supervisor")  # each subgraph reports back
builder.add_edge("assess", "supervisor")
graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({"request": "a research data management group"})
    print(result["assessment"])
