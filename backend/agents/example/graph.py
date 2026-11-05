"""Example agentic graph: a supervisor with tools and one subagent.

    START -> supervisor --(tool calls?)--> tools -> supervisor ... -> END
                                            |
                                            +-- calculator, current_time   (plain tools)
                                            +-- writer                     (subagent graph)

Copy this file as the starting point for your own graph. The app needs only:
  1. a state with a `messages` key (MessagesState or a subclass),
  2. the LLM from `get_model(config)` instead of a hard-coded client,
  3. `config` passed along to subagents (subagent_tool does this for you).
Export the uncompiled `builder` (the app compiles it with its Postgres checkpointer) or a
compiled `graph`.
"""

import ast
import operator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agentkit import get_model, subagent_tool

# ------------------------------------------------------------------ plain tools

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only numbers and + - * / % ** are allowed")


@tool
def calculator(expression: str) -> str:
    """Evaluate an arithmetic expression such as '(17 * 23) / 4'. Use it for any math."""
    try:
        return str(_eval(ast.parse(expression, mode="eval").body))
    except (SyntaxError, ValueError, ZeroDivisionError) as exc:
        return f"Error: {exc}"


@tool
def current_time(timezone: str = "UTC") -> str:
    """Current date and time in an IANA timezone such as 'Asia/Kolkata' or 'America/New_York'."""
    try:
        return datetime.now(ZoneInfo(timezone)).isoformat(timespec="seconds")
    except ZoneInfoNotFoundError:
        return f"Error: unknown timezone {timezone!r}"


# ------------------------------------------------------------------ subagent: writer

WRITER_PROMPT = (
    "You are a careful writer. Produce exactly the text you are asked for: clear, concise, "
    "well structured. Return only the finished text."
)


async def writer_node(state: MessagesState, config: RunnableConfig) -> dict:
    model = get_model(config)
    reply = await model.ainvoke([SystemMessage(WRITER_PROMPT), *state["messages"]], config)
    return {"messages": [reply]}


writer_builder = StateGraph(MessagesState)
writer_builder.add_node("writer", writer_node)
writer_builder.add_edge(START, "writer")
writer = writer_builder.compile(name="writer")

# ------------------------------------------------------------------ supervisor

TOOLS = [
    calculator,
    current_time,
    subagent_tool(
        writer,
        name="writer",
        description="Delegate drafting or rewriting a piece of text (emails, summaries, "
        "poems, docs) to a writing specialist. Give it the full brief.",
    ),
]

SUPERVISOR_PROMPT = (
    "You are a helpful assistant that coordinates tools and specialists. Use the calculator "
    "for arithmetic, current_time for dates and times, and the writer for substantial "
    "writing tasks. Answer directly when no tool is needed."
)


async def supervisor(state: MessagesState, config: RunnableConfig) -> dict:
    model = get_model(config).bind_tools(TOOLS)
    reply = await model.ainvoke([SystemMessage(SUPERVISOR_PROMPT), *state["messages"]], config)
    return {"messages": [reply]}


builder = StateGraph(MessagesState)
builder.add_node("supervisor", supervisor)
builder.add_node("tools", ToolNode(TOOLS))
builder.add_edge(START, "supervisor")
builder.add_conditional_edges("supervisor", tools_condition)
builder.add_edge("tools", "supervisor")

# Compiled without a checkpointer, for notebooks and `langgraph dev`.
graph = builder.compile()
