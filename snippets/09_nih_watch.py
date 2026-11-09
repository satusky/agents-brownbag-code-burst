"""Putting it together: Send workers route items; a person approves before posting.

fetch (code) → route × N (model, in parallel) → approve (person) → post (code)
"""

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt
from pydantic import BaseModel

from brown_bag_demos.models import get_model

llm = get_model()


class Route(BaseModel):
    group: Literal["analytics", "networking", "software", "none"]


router = llm.with_structured_output(Route)


class State(TypedDict):
    titles: list[str]
    messages: Annotated[list[str], operator.add]  # each worker adds its message
    approved: bool


class Item(TypedDict):
    title: str


def fetch(state: State) -> dict:  # code: the real stage reads NIH's new postings
    return {"titles": ["Cloud platform for genomic data sharing",
                       "Nurse staffing intervention trial",
                       "Secure networks for clinical research data"]}


def assign(state: State) -> list[Send]:
    return [Send("route", {"title": t}) for t in state["titles"]]  # one worker per item


def route(state: Item) -> dict:
    choice = router.invoke("Which group should see this? Answer none unless it is "
                           f"mainly data or computing work.\n{state['title']}")
    if choice.group == "none":
        return {"messages": []}
    return {"messages": [f"#{choice.group}: {state['title']}"]}


def approve(state: State) -> dict:
    answer = interrupt(state["messages"])  # pause: a person checks every message
    return {"approved": answer == "yes"}


def after_approve(state: State) -> str:
    return "post" if state["approved"] else END


def post(state: State) -> dict:  # code: the real stage posts to Slack
    for message in state["messages"]:
        print("posted", message)
    return {}


builder = StateGraph(State)
builder.add_node("fetch", fetch)
builder.add_node("route", route)
builder.add_node("approve", approve)
builder.add_node("post", post)
builder.add_edge(START, "fetch")
builder.add_conditional_edges("fetch", assign, ["route"])
builder.add_edge("route", "approve")
builder.add_conditional_edges("approve", after_approve, ["post", END])
builder.add_edge("post", END)
graph = builder.compile(checkpointer=InMemorySaver())


if __name__ == "__main__":
    config = {"configurable": {"thread_id": "demo"}}
    result = graph.invoke({}, config)
    print("\n".join(result["__interrupt__"][0].value))
    answer = input("\nPost these? (yes/no): ").strip()
    graph.invoke(Command(resume=answer), config)
