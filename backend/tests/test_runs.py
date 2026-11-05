from langchain_core.messages import AIMessage

from tests.conftest import new_thread, run


def texts(events, parent=None):
    return "".join(
        e["delta"] for e in events if e["type"] == "text" and e["parent_tool_call_id"] == parent
    )


async def test_supervisor_tool_subagent_stream(client):
    thread_id = await new_thread(client)
    events = await run(client, thread_id, "Write me a haiku")
    types = [e["type"] for e in events]

    assert types[0] == "run_start" and events[0]["protocol"] == 1
    assert types[1] == "user_message"
    assert events[1]["message"]["parts"] == [{"type": "text", "text": "Write me a haiku"}]
    assert types[-1] == "done" and events[-1]["status"] == "complete"

    # The supervisor's own words, token by token, then the final answer.
    assert texts(events) == "Let me ask the writer.Here is your haiku."
    # The tool call, with complete args, before the subagent starts.
    call = next(e for e in events if e["type"] == "tool_call")
    assert call["name"] == "writer" and call["args"] == {"task": "Write a haiku"}
    assert call["parent_tool_call_id"] is None
    # The subagent's tokens are nested under the tool call that started it.
    sub = [e for e in events if e["type"] == "text" and e["parent_tool_call_id"] == "call_1"]
    assert "".join(e["delta"] for e in sub) == "Leaves fall softly down"
    assert {e["agent"] for e in sub} == {"writer"} and sub[0]["ns"][0] == "tools"
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["tool_call_id"] == "call_1" and result["content"] == "Leaves fall softly down"
    assert result["status"] == "success"
    assert types.index("tool_call") < types.index("tool_result")

    # Node progress for the root graph.
    roots = [e["node"] for e in events if e["type"] == "step_start" and not e["ns"]]
    assert roots == ["supervisor", "tools", "supervisor"]


async def test_first_turn_sets_title(client):
    thread_id = await new_thread(client)
    events = await run(client, thread_id, "Write me a haiku")
    title = next(e for e in events if e["type"] == "title")["title"]
    assert title  # the script is used up, so the model echoes; any non-empty title will do
    threads = (await client.get("/api/threads")).json()
    assert threads[0]["id"] == thread_id and threads[0]["title"] == title
    assert threads[0]["model"] == "fake:script"


async def test_history_rebuilds_turns_with_timestamps(client):
    thread_id = await new_thread(client)
    await run(client, thread_id, "Write me a haiku")
    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    user, assistant = detail["messages"]
    assert user["role"] == "user" and user["parts"][0]["text"] == "Write me a haiku"
    assert user["created_at"] and assistant["created_at"]
    assert assistant["created_at"] >= user["created_at"]
    kinds = [p["type"] for p in assistant["parts"]]
    assert kinds == ["text", "tool", "text"]
    tool = assistant["parts"][1]
    assert tool["name"] == "writer" and tool["status"] == "success"
    assert tool["result"] == "Leaves fall softly down"
    # The subagent's own work survives a reload (kept as the tool message artifact).
    assert tool["agent"] == "writer"
    assert tool["parts"] == [{"type": "text", "text": "Leaves fall softly down"}]
    assert assistant["parts"][2]["text"] == "Here is your haiku."


async def test_follow_up_turn_sees_history(client, script):
    script[:] = [AIMessage("first"), AIMessage("title"), AIMessage("second")]
    thread_id = await new_thread(client)
    await run(client, thread_id, "one")
    await run(client, thread_id, "two")
    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][3]["parts"][0]["text"] == "second"


async def test_thinking_streams_reasoning(client, script):
    script[:] = [AIMessage("Answer.")]
    thread_id = await new_thread(client, thinking=True)
    events = await run(client, thread_id, "hi")
    reasoning = "".join(e["delta"] for e in events if e["type"] == "reasoning")
    assert reasoning.strip() == "Pondering it."
    assert events[0]["thinking"] is True
    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    assert detail["thinking"] is True
    assert [p["type"] for p in detail["messages"][1]["parts"]] == ["reasoning", "text"]


async def test_run_errors_are_reported(client, settings):
    thread_id = await new_thread(client)
    events = await run(client, thread_id, "hi", model="ollama:missing")
    assert events[-1] == {"type": "done", "status": "error"}
    assert any(e["type"] == "error" for e in events)


async def test_bad_model_id_is_rejected(client):
    thread_id = await new_thread(client)
    response = await client.post(
        f"/api/threads/{thread_id}/runs", json={"content": "hi", "model": "nope"}
    )
    assert response.status_code == 400


async def test_unknown_thread_404(client):
    response = await client.post(
        "/api/threads/00000000-0000-0000-0000-000000000000/runs", json={"content": "hi"}
    )
    assert response.status_code == 404
