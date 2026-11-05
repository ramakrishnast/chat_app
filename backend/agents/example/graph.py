"""Example: a one-node graph whose node is a supervisor agent with tools and a subagent.

    START -> supervisor (create_agent: model + tools + middleware) -> END
                 tools: calculator, current_time, writer (a subagent, also create_agent)

Add your own tools and middleware to the create_agent calls; add more nodes to `builder`
when you need steps before or after the supervisor. The app needs only:
  1. a state with `messages` (MessagesState here),
  2. UseChatModel() in each agent's middleware, so it runs on the model picked in the UI,
  3. subagents wrapped with subagent_tool(), so their work shows under the tool call.
"""

import ast
import operator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.agents import create_agent
from langchain_core.tools import tool
from langgraph.graph import START, MessagesState, StateGraph

from agentkit import UseChatModel, default_model, subagent_tool

# ------------------------------------------------------------------ tools

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


# ------------------------------------------------------------------ subagent

writer = create_agent(
    model=default_model(),
    system_prompt=(
        "You are a careful writer. Produce exactly the text you are asked for: clear, "
        "concise, well structured. Return only the finished text."
    ),
    middleware=[UseChatModel()],
    name="writer",
)

# ------------------------------------------------------------------ supervisor

supervisor = create_agent(
    model=default_model(),
    tools=[
        calculator,
        current_time,
        subagent_tool(
            writer,
            name="writer",
            description="Delegate drafting or rewriting a piece of text (emails, summaries, "
            "poems, docs) to a writing specialist. Give it the full brief.",
        ),
    ],
    system_prompt=(
        "You are a helpful assistant that coordinates tools and specialists. Use the "
        "calculator for arithmetic, current_time for dates and times, and the writer for "
        "substantial writing tasks. Answer directly when no tool is needed."
    ),
    middleware=[UseChatModel()],  # add yours: SummarizationMiddleware, ModelRetryMiddleware...
    name="supervisor",
)

# ------------------------------------------------------------------ the graph

builder = StateGraph(MessagesState)
builder.add_node("supervisor", supervisor)
builder.add_edge(START, "supervisor")

# Compiled without a checkpointer, for notebooks and `langgraph dev`.
graph = builder.compile()
