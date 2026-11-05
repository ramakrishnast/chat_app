"""Pressing stop closes the stream; the thread must keep the partial answer and stay usable."""

from langchain_core.messages import AIMessage, ToolMessage

from app.runs import run_config, stream_run
from tests.conftest import new_thread, parse_sse


async def start(client, thread_id, content="go"):
    app = client.app
    return stream_run(
        graph=app.state.graph,
        store=app.state.store,
        thread_id=thread_id,
        content=content,
        model_id="fake:script",
        thinking=False,
        first_turn=False,
        placeholder_title="x",
        active=app.state.runs.active,
    )


async def stop_after(stream, predicate):
    seen = []
    async for chunk in stream:
        seen += parse_sse(chunk)
        if predicate(seen[-1]):
            break
    await stream.aclose()  # what the server does when the browser aborts the request
    return seen


async def test_stop_mid_answer_keeps_partial_text(client, script, model):
    script[:] = [AIMessage("one two three four five six"), AIMessage("after stop")]
    thread_id = await new_thread(client)
    stream = await start(client, thread_id)
    await stop_after(stream, lambda e: e["type"] == "text" and "three" in e["delta"])
    assert thread_id not in client.app.state.runs.active

    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    assistant = detail["messages"][1]
    assert assistant["status"] == "stopped"
    assert assistant["parts"][0]["text"] == "one two three "

    # The next turn works and sees the stopped reply in its history.
    response = await client.post(f"/api/threads/{thread_id}/runs", json={"content": "again"})
    assert parse_sse(response.text)[-1]["status"] == "complete"
    roles = [m["role"] for m in (await client.get(f"/api/threads/{thread_id}")).json()["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]


async def test_stop_during_subagent_answers_the_tool_call(client):
    thread_id = await new_thread(client)
    stream = await start(client, thread_id)
    await stop_after(stream, lambda e: e["type"] == "text" and e["parent_tool_call_id"])

    state = await client.app.state.graph.aget_state(run_config(thread_id, "fake:script", False))
    messages = state.values["messages"]
    calls = [c["id"] for m in messages if isinstance(m, AIMessage) for c in m.tool_calls]
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    assert calls == ["call_1"] and results["call_1"].status == "error"
    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    assert detail["messages"][1]["status"] == "stopped"
    assert detail["messages"][1]["parts"][1]["status"] == "error"

    response = await client.post(f"/api/threads/{thread_id}/runs", json={"content": "again"})
    assert parse_sse(response.text)[-1]["status"] == "complete"
