"""Routing: the model picks a label; a conditional edge turns it into a path.

route (model) → analytics | networking | software
"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from brown_bag_demos.models import get_model

llm = get_model()


class Route(BaseModel):
    group: Literal["analytics", "networking", "software"]


router = llm.with_structured_output(Route)  # the answer must be one of the labels


class State(TypedDict):
    opportunity: str
    group: str
    note: str


def route(state: State) -> dict:
    choice = router.invoke(f"Which group should take this?\n{state['opportunity']}")
    return {"group": choice.group}


def analytics(state: State) -> dict:
    reply = llm.invoke(f"Write a note to the Analytics group:\n{state['opportunity']}")
    return {"note": reply.text}


def networking(state: State) -> dict:
    reply = llm.invoke(f"Write a note to the Networking group:\n{state['opportunity']}")
    return {"note": reply.text}


def software(state: State) -> dict:
    reply = llm.invoke(f"Write a note to the Software group:\n{state['opportunity']}")
    return {"note": reply.text}


def pick_group(state: State) -> str:
    return state["group"]  # the label is the name of the next node


builder = StateGraph(State)
builder.add_node("route", route)
builder.add_node("analytics", analytics)
builder.add_node("networking", networking)
builder.add_node("software", software)
builder.add_edge(START, "route")
builder.add_conditional_edges("route", pick_group,
                              ["analytics", "networking", "software"])
builder.add_edge("analytics", END)
builder.add_edge("networking", END)
builder.add_edge("software", END)
graph = builder.compile()


if __name__ == "__main__":
    opportunity = "Network research testbeds: programmable 100G links between campuses."
    result = graph.invoke({"opportunity": opportunity})
    print(f"→ {result['group']}\n\n{result['note']}")
