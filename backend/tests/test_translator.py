"""Attribution rules that don't need the full app."""

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.streaming import StreamTranslator


def msg(ns, chunk, **meta):
    return {"type": "messages", "ns": ns, "data": (chunk, meta)}


def upd(ns, node, *messages):
    return {"type": "updates", "ns": ns, "data": {node: {"messages": list(messages)}}}


def test_plain_subgraph_in_tool_is_attributed_to_running_call():
    t = StreamTranslator()
    call = AIMessage("", id="a1", tool_calls=[{"name": "research", "args": {}, "id": "c9"}])
    assert t.feed(upd((), "agent", call))[0]["tool_call_id"] == "c9"
    # A subgraph run inside the tool without subagent_tool(): no metadata, nested namespace.
    events = t.feed(msg(("tools:x",), AIMessageChunk("found it", id="s1")))
    assert events[0]["parent_tool_call_id"] == "c9" and events[0]["agent"] is None
    t.feed(upd((), "tools", ToolMessage("found it", tool_call_id="c9", name="research")))
    # Once the tool finished, text is the main answer again.
    assert t.feed(msg((), AIMessageChunk("done", id="a2")))[0]["parent_tool_call_id"] is None


def test_agent_used_as_a_node_is_the_main_answer():
    # create_agent()/a compiled graph added as a node: tokens come with a namespace but no
    # tool call is running, so they are the answer.
    t = StreamTranslator()
    events = t.feed(msg(("supervisor:1",), AIMessageChunk("hello", id="m1")))
    assert events[0]["parent_tool_call_id"] is None and events[0]["ns"] == ["supervisor"]


def test_duplicates_and_empty_chunks_are_dropped():
    t = StreamTranslator()
    assert t.feed(msg((), AIMessageChunk("", id="m1"))) == []
    call = AIMessage("", id="a1", tool_calls=[{"name": "x", "args": {}, "id": "c1"}])
    assert len(t.feed(upd((), "agent", call))) == 1
    assert t.feed(upd(("sub:1",), "agent", call)) == []


def test_unfinished_answer_tracks_text_not_in_state():
    t = StreamTranslator()
    t.feed(msg((), AIMessageChunk("partial ", id="m1")))
    t.feed(msg((), AIMessageChunk("text", id="m1")))
    assert t.unfinished_answer() == ("m1", "partial text")
    t.feed(upd((), "agent", AIMessage("partial text", id="m1")))
    assert t.unfinished_answer() is None
