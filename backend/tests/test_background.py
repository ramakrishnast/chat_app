"""Replies run on the server: watchers can leave and come back; only Stop ends them early."""

import asyncio

from langchain_core.messages import AIMessage

from app.runs import stream_run
from tests.conftest import new_thread, parse_sse


def start(client, thread_id, content="go"):
    app = client.app
    runs = app.state.runs
    return runs.start(
        thread_id,
        stream_run(
            graph=app.state.graph,
            store=app.state.store,
            thread_id=thread_id,
            content=content,
            model_id="fake:script",
            thinking=False,
            first_turn=False,
            placeholder_title="x",
            active=runs.active,
        ),
    )


async def first_text(run):
    watcher = run.subscribe()
    async for chunk in watcher:
        if parse_sse(chunk)[0]["type"] == "text":
            break
    await watcher.aclose()  # the browser left: switched chat, reloaded, closed the tab


async def test_reply_finishes_after_the_watcher_leaves(client, script, model):
    model.delay = 0.01
    script[:] = [AIMessage("one two three four five six seven eight")]
    thread_id = await new_thread(client)
    run = start(client, thread_id)
    await first_text(run)
    assert client.app.state.runs.get(thread_id) is run  # still running
    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    assert detail["running"] is True

    await asyncio.wait_for(run.task, 10)
    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    assert detail["running"] is False
    assistant = detail["messages"][1]
    assert assistant["status"] == "complete"
    assert assistant["parts"][0]["text"] == "one two three four five six seven eight"


async def test_rejoining_replays_the_whole_reply(client, script, model):
    model.delay = 0.01
    script[:] = [AIMessage("alpha beta gamma delta")]
    thread_id = await new_thread(client)
    run = start(client, thread_id)
    await first_text(run)
    events = [e for chunk in [c async for c in run.subscribe()] for e in parse_sse(chunk)]
    assert events[0]["type"] == "run_start" and events[1]["type"] == "user_message"
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert text == "alpha beta gamma delta" and events[-1] == {"type": "done", "status": "complete"}
    # Nothing running any more: the live endpoint says so.
    assert (await client.get(f"/api/threads/{thread_id}/runs/live")).status_code == 204


async def test_stop_endpoint_keeps_the_partial_reply(client, script, model):
    model.delay = 0.05
    script[:] = [AIMessage("one two three four five six seven eight nine ten")]
    thread_id = await new_thread(client)
    run = start(client, thread_id)
    await first_text(run)
    response = await client.post(f"/api/threads/{thread_id}/runs/stop")
    assert response.json() == {"stopped": True}
    assert parse_sse(run.events[-1])[0] == {"type": "done", "status": "stopped"}

    assistant = (await client.get(f"/api/threads/{thread_id}")).json()["messages"][1]
    assert assistant["status"] == "stopped" and assistant["parts"][0]["text"]
    assert (await client.post(f"/api/threads/{thread_id}/runs/stop")).json() == {"stopped": False}


async def test_one_reply_at_a_time_and_delete_stops_it(client, script, model):
    model.delay = 0.05
    script[:] = [AIMessage("a b c d e f g h i j")]
    thread_id = await new_thread(client)
    run = start(client, thread_id)
    response = await client.post(f"/api/threads/{thread_id}/runs", json={"content": "again"})
    assert response.status_code == 409
    assert (await client.delete(f"/api/threads/{thread_id}")).status_code == 204
    assert run.done
