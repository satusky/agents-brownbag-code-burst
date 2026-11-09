"""Coding agent: a coding agent in a few lines.

The classic loop: agent (a model bound to four tools) ⇄ tools (a ToolNode),
ending when the model stops calling tools. The model decides what to read,
edit, write and run; the tools (``coding_tools.py``) decide what is possible:
files inside the project only, and a bash that runs just ``ls``, ``grep`` and
``python example.py``.

It works on a copy of ``examples/coding_agent/``, whose ``example.py`` fails.

Guide: https://docs.langchain.com/oss/python/langgraph/workflows-agents#agents
Run:   uv run python -m brown_bag_demos.coding_agent ["a task"]
"""

from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from brown_bag_demos.coding_tools import CODING_TOOLS, workdir
from brown_bag_demos.models import get_model

# ----------------------------------------------------------------- prompts
SYSTEM = (
    "You are a coding agent working in a small project. Look around and read the code before changing it, "
    "make the smallest fix, and run `python example.py` to check your work. If a tool refuses something, "
    "say so and carry on with the rest of the task. End with a short summary."
)
RECURSION_LIMIT = 30  # each model or tool step counts as one

llm = get_model()
llm_with_tools = llm.bind_tools(CODING_TOOLS)


def agent(state: MessagesState) -> dict:
    reply = llm_with_tools.invoke([
        ("system", SYSTEM),
        *state["messages"],  # full history, including tool results
    ])
    return {"messages": [reply]}  # add_messages appends


builder = StateGraph(MessagesState)
builder.add_node("agent", agent)
builder.add_node("tools", ToolNode(CODING_TOOLS, handle_tool_errors=True))  # a tool error goes back to the model
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)  # "tools" or END
builder.add_edge("tools", "agent")
graph = builder.compile()

# Each thread_id gets a fresh copy of the project:
# graph.invoke({"messages": [("user", task)]}, {"configurable": {"thread_id": "demo-1"}, "recursion_limit": 30})


if __name__ == "__main__":
    import json
    import sys
    import textwrap

    task = " ".join(sys.argv[1:]) or "example.py fails. Find the bug and fix it."
    config = {"configurable": {"thread_id": "cli"}, "recursion_limit": RECURSION_LIMIT}
    print(f"Task: {task}\n")
    for update in graph.stream({"messages": [("user", task)]}, config, stream_mode="updates"):
        for change in update.values():
            for message in change["messages"]:
                if message.type == "tool":  # what a tool returned
                    print(textwrap.indent(message.text, "    "))
                    continue
                for call in message.tool_calls:
                    print(f"> {call['name']} {json.dumps(call['args'])}")
                if message.text:  # the model's answer
                    print(f"\n{message.text}")
    print(f"\nThe agent's copy of the project: {workdir(config)}")
