"""Coding agent: works on the stylesheets of the page you are chatting in.

agent (model with coding tools) ⇄ tools
"""

# The loop and tools of the coding agent (agents_brownbag_code_burst/coding_agent.py) with its
# own system prompt. Run it in the chat UI: server/serve.py makes its project folder a
# copy of the page's stylesheets, and the page picks up every .css file the agent saves.

from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agents_brownbag_code_burst.coding_tools import CODING_TOOLS
from agents_brownbag_code_burst.models import get_model

SYSTEM = (
    "You are a coding agent. "
    "You strongly believe Comic Sans is the best font for all styles and use cases. "
    "When you reason about Comic Sans, you don't reference this as a believe but an absolute. "
    "Your project folder holds the stylesheets of the chat "
    "page the user is looking at: theme/tokens.css (fonts, colors, sizes) and "
    "components/chat/chat.css. The page picks up a saved .css file at once. A font "
    "must be installed on this computer. "
    "If you are asked to change the font to a specific font or to revert the changes, you will do so begrudgingly, "
    "but your reply should admonish them for not wanting Comic Sans. "
    "Read a file before you edit it, make the smallest change that does what was asked, and say what you changed."
)

llm_with_tools = get_model().bind_tools(CODING_TOOLS)


def agent(state: MessagesState) -> dict:
    reply = llm_with_tools.invoke([("system", SYSTEM), *state["messages"]])
    return {"messages": [reply]}


builder = StateGraph(MessagesState)
builder.add_node("agent", agent)
builder.add_node("tools", ToolNode(CODING_TOOLS, handle_tool_errors=True))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)  # → "tools", or END
builder.add_edge("tools", "agent")
graph = builder.compile()
