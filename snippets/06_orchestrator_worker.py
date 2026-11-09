"""Orchestrator-worker: a model plans the subtasks, and Send starts one worker for each.

plan (model) → worker × N (in parallel) → collect
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel

from brown_bag_demos.models import get_model

llm = get_model()


class Plan(BaseModel):
    groups: list[str]


planner = llm.with_structured_output(Plan)


class State(TypedDict):
    profile: str
    groups: list[str]
    findings: Annotated[list[str], operator.add]  # each worker's list is added on
    summary: str


class WorkerState(TypedDict):
    group: str


def plan(state: State) -> dict:
    result = planner.invoke(f"List the research groups named in:\n{state['profile']}")
    return {"groups": result.groups}


def assign_workers(state: State) -> list[Send]:
    return [Send("worker", {"group": g}) for g in state["groups"]]  # one per group


def worker(state: WorkerState) -> dict:
    prompt = f"Name 3 funding search keywords for {state['group']}, comma-separated."
    reply = llm.invoke(prompt)
    return {"findings": [f"{state['group']}: {reply.text}"]}


def collect(state: State) -> dict:
    return {"summary": "\n".join(state["findings"])}  # runs once, after every worker


builder = StateGraph(State)
builder.add_node("plan", plan)
builder.add_node("worker", worker)
builder.add_node("collect", collect)
builder.add_edge(START, "plan")
builder.add_conditional_edges("plan", assign_workers, ["worker"])  # fan out with Send
builder.add_edge("worker", "collect")
builder.add_edge("collect", END)
graph = builder.compile()


if __name__ == "__main__":
    profile = ("RENCI has three research groups: Earth Data Science, "
               "Networking Research, and Software Architecture.")
    print(graph.invoke({"profile": profile})["summary"])
