"""Agent: the model decides which tools to call, in a loop, until it is done.

agent (model with tools) ⇄ tools
"""

from datetime import date

from langchain_core.tools import tool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from brown_bag_demos.models import get_model


@tool
def search_opportunities(keywords: str) -> str:
    """Search funding opportunities by keywords."""
    # A stand-in: a real tool would call Grants.gov here.
    return "DEMO-101 Climate Data Cyberinfrastructure: letter of intent due 2026-12-01"


@tool
def days_until(day: str) -> int:
    """Count the days from today until a date written as YYYY-MM-DD."""
    return (date.fromisoformat(day) - date.today()).days


tools = [search_opportunities, days_until]
# The model sees each tool's name, arguments and docstring.
llm_with_tools = get_model().bind_tools(tools)


def agent(state: MessagesState) -> dict:
    reply = llm_with_tools.invoke(state["messages"])  # the whole conversation so far
    return {"messages": [reply]}


builder = StateGraph(MessagesState)
builder.add_node("agent", agent)
builder.add_node("tools", ToolNode(tools))  # runs the tool calls the model asked for
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)  # → "tools", or END
builder.add_edge("tools", "agent")  # tool results go back to the model
graph = builder.compile()


if __name__ == "__main__":
    question = "Find a climate data opportunity. How many days until it is due?"
    result = graph.invoke({"messages": [("user", question)]})
    print(result["messages"][-1].text)
