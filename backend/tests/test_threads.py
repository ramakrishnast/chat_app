from tests.conftest import new_thread, run


async def test_thread_crud(client):
    thread_id = await new_thread(client, model="fake:echo")
    listed = (await client.get("/api/threads")).json()
    assert [t["id"] for t in listed] == [thread_id] and listed[0]["title"] == "New chat"

    renamed = await client.patch(f"/api/threads/{thread_id}", json={"title": "Renamed"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Renamed"

    detail = (await client.get(f"/api/threads/{thread_id}")).json()
    assert detail["messages"] == [] and detail["model"] == "fake:echo"

    assert (await client.delete(f"/api/threads/{thread_id}")).status_code == 204
    assert (await client.get(f"/api/threads/{thread_id}")).status_code == 404


async def test_delete_removes_checkpoints(client):
    thread_id = await new_thread(client)
    await run(client, thread_id, "Write me a haiku")
    await client.delete(f"/api/threads/{thread_id}")
    state = await client.app.state.graph.aget_state({"configurable": {"thread_id": thread_id}})
    assert not state.values


async def test_models_and_info(client):
    body = (await client.get("/api/models")).json()
    assert {
        "id": "fake:echo",
        "provider": "fake",
        "name": "echo",
        "thinking": True,
        "detail": None,
    } in body["models"]
    assert body["default"] == "fake:script"  # DEFAULT_MODEL wins
    info = (await client.get("/api/info")).json()
    assert info["protocol"] == 1 and info["graph"] == "agents.example.graph:builder"
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_serves_built_ui_next_to_the_api(tmp_path, model):
    import httpx

    from app.main import create_app
    from tests.conftest import make_settings

    (tmp_path / "index.html").write_text("<div id=root></div>")
    app = create_app(make_settings(frontend_dist=tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            assert "id=root" in (await c.get("/")).text
            assert (await c.get("/health")).json() == {"status": "ok"}
            assert (await c.get("/api/threads")).json() == []
