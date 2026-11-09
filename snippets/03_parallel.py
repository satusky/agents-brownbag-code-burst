"""Parallelization: independent steps run at the same time, then join.

START → check_fit + check_eligibility (in parallel) → recommend
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from brown_bag_demos.models import get_model

llm = get_model()


class State(TypedDict):
    opportunity: str
    profile: str
    fit: str          # each branch writes its own key,
    eligibility: str  # so parallel writes never collide
    recommendation: str


def check_fit(state: State) -> dict:
    reply = llm.invoke(
        f"Does this profile match the opportunity? Two sentences.\n"
        f"PROFILE: {state['profile']}\nOPPORTUNITY: {state['opportunity']}"
    )
    return {"fit": reply.text}


def check_eligibility(state: State) -> dict:
    reply = llm.invoke(
        f"Can this applicant apply? Two sentences.\n"
        f"PROFILE: {state['profile']}\nOPPORTUNITY: {state['opportunity']}"
    )
    return {"eligibility": reply.text}


def recommend(state: State) -> dict:
    reply = llm.invoke(
        f"Combine these into one recommendation:\n"
        f"FIT: {state['fit']}\nELIGIBILITY: {state['eligibility']}"
    )
    return {"recommendation": reply.text}


builder = StateGraph(State)
builder.add_node("check_fit", check_fit)
builder.add_node("check_eligibility", check_eligibility)
builder.add_node("recommend", recommend)
builder.add_edge(START, "check_fit")          # two edges out of START:
builder.add_edge(START, "check_eligibility")  # both run at the same time
builder.add_edge(["check_fit", "check_eligibility"], "recommend")  # waits for both
builder.add_edge("recommend", END)
graph = builder.compile()


if __name__ == "__main__":
    opportunity = "Climate data platforms. Universities may apply. Due 2027-02-15."
    profile = "RENCI, a research institute at UNC-Chapel Hill: data science, computing."
    result = graph.invoke({"opportunity": opportunity, "profile": profile})
    print(result["recommendation"])
