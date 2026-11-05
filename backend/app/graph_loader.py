"""Import the user's graph from GRAPH="module:attr" and attach the app's checkpointer."""

import importlib
import inspect
import os
import sys
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph
from langgraph.pregel import Pregel


class GraphLoadError(Exception):
    pass


def _extend_sys_path(paths: list[str]) -> None:
    for path in paths:
        resolved = os.path.realpath(os.path.expanduser(path))
        if resolved not in sys.path:
            sys.path.insert(0, resolved)


async def load_graph(
    spec: str, checkpointer: BaseCheckpointSaver, extra_paths: list[str]
) -> Pregel:
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name or not attr:
        raise GraphLoadError(f"GRAPH={spec!r} must look like 'package.module:attribute'")
    _extend_sys_path(extra_paths)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise GraphLoadError(f"Could not import {module_name!r} for GRAPH: {exc}") from exc
    try:
        obj: Any = getattr(module, attr)
    except AttributeError as exc:
        raise GraphLoadError(f"{module_name!r} has no attribute {attr!r}") from exc

    # A factory: call it (and await it if it's async).
    if callable(obj) and not isinstance(obj, StateGraph | Pregel):
        obj = obj()
        if inspect.isawaitable(obj):
            obj = await obj

    if isinstance(obj, StateGraph):
        graph = obj.compile(checkpointer=checkpointer)
    elif isinstance(obj, Pregel):
        # Same graph, our checkpointer: threads and history need one.
        graph = obj.copy(update={"checkpointer": checkpointer})
    else:
        raise GraphLoadError(
            f"GRAPH {spec!r} is a {type(obj).__name__}; expected a StateGraph, a compiled "
            "graph, or a factory returning one"
        )

    if "messages" not in graph.channels:
        raise GraphLoadError(
            f"GRAPH {spec!r} has no 'messages' state key. Use MessagesState (or add "
            "`messages: Annotated[list[AnyMessage], add_messages]`) so it can hold a chat."
        )
    return graph
