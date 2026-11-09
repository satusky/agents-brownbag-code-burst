"""Custom workflow: code makes every decision it can; the model judges only the rest.

screen (code) → score (code) → judge (model, only if needed) → report (code)
"""

from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from brown_bag_demos.models import get_model

KEYWORDS = {"data", "network", "software", "computing"}

llm = get_model()


class State(TypedDict):
    opportunities: list[dict]
    fits: list[dict]
    unclear: list[dict]
    result: str


def screen(state: State) -> dict:  # code: drop what has already closed
    today = date.today().isoformat()
    still_open = [o for o in state["opportunities"] if o["deadline"] >= today]
    return {"opportunities": still_open}


def score(state: State) -> dict:  # code: a keyword match settles the clear cases
    fits, unclear = [], []
    for o in state["opportunities"]:
        if KEYWORDS & set(o["title"].lower().split()):
            fits.append(o)
        else:
            unclear.append(o)
    return {"fits": fits, "unclear": unclear}


def needs_judge(state: State) -> str:  # code: is the model needed at all?
    return "judge" if state["unclear"] else "report"


def judge(state: State) -> dict:  # model: only the items code could not settle
    fits = list(state["fits"])
    for o in state["unclear"]:
        question = f"Is this mainly data or computing work? Yes or no: {o['title']}"
        if llm.invoke(question).text.lower().startswith("yes"):  # code reads the answer
            fits.append(o)
    return {"fits": fits}


def report(state: State) -> dict:  # code: a table built from data
    rows = sorted(state["fits"], key=lambda o: o["deadline"])
    return {"result": "\n".join(f"{o['deadline']}  {o['title']}" for o in rows)}


builder = StateGraph(State)
builder.add_node("screen", screen)
builder.add_node("score", score)
builder.add_node("judge", judge)
builder.add_node("report", report)
builder.add_edge(START, "screen")
builder.add_edge("screen", "score")
builder.add_conditional_edges("score", needs_judge, ["judge", "report"])
builder.add_edge("judge", "report")
builder.add_edge("report", END)
graph = builder.compile()


if __name__ == "__main__":
    opportunities = [
        {"title": "Climate data platforms", "deadline": "2027-02-15"},
        {"title": "Network research testbeds", "deadline": "2027-03-01"},
        {"title": "Research software sustainability", "deadline": "2026-10-01"},
        {"title": "Pediatric clinical trial planning", "deadline": "2027-01-10"},
        {"title": "Digital twins of coastal ecosystems", "deadline": "2027-04-30"},
    ]
    print(graph.invoke({"opportunities": opportunities})["result"])
