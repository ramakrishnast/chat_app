import sys
import types

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from typing_extensions import TypedDict

from app.graph_loader import GraphLoadError, load_graph


class NoMessages(TypedDict):
    question: str


def register(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module


async def test_accepts_builder_compiled_and_factory():
    from agents.example.graph import builder

    saver = InMemorySaver()
    register(
        "fake_graphs",
        builder=builder,
        compiled=builder.compile(),
        factory=lambda: builder,
        afactory=lambda: _async(builder),
    )
    for attr in ("builder", "compiled", "factory", "afactory"):
        graph = await load_graph(f"fake_graphs:{attr}", saver, [])
        assert graph.checkpointer is saver


async def _async(value):
    return value


async def test_rejects_state_without_messages():
    b = StateGraph(NoMessages)
    b.add_node("n", lambda s: {})
    b.add_edge(START, "n")
    register("bad_graphs", builder=b)
    with pytest.raises(GraphLoadError, match="messages"):
        await load_graph("bad_graphs:builder", InMemorySaver(), [])


@pytest.mark.parametrize("spec", ["nocolon", "missing_mod_xyz:graph", "fake_graphs:nope"])
async def test_bad_specs(spec):
    with pytest.raises(GraphLoadError):
        await load_graph(spec, InMemorySaver(), [])
