# Stream contract (protocol 1)

The frontend talks to the backend only through this contract. `frontend/src/contract.ts`
mirrors it in TypeScript; nothing else in the UI knows about LangGraph.

## REST

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/health` | | `{"status": "ok"}` |
| GET | `/api/info` | | `{protocol, graph, storage}` |
| GET | `/api/models?refresh=true` | | `{models: ModelInfo[], default}` |
| GET | `/api/threads` | | `Thread[]`, most recently used first |
| POST | `/api/threads` | `{title?, model?, thinking?}` | `Thread` (201) |
| GET | `/api/threads/{id}` | | `Thread & {messages: ChatMessage[], running}` |
| PATCH | `/api/threads/{id}` | `{title?, model?, thinking?}` | `Thread` |
| DELETE | `/api/threads/{id}` | | 204 (also deletes the LangGraph checkpoints) |
| POST | `/api/threads/{id}/runs` | `{content, model?, thinking?}` | `text/event-stream` |
| GET | `/api/threads/{id}/runs/live` | | `text/event-stream` of the running reply, or 204 |
| POST | `/api/threads/{id}/runs/stop` | | `{stopped: bool}` |

Errors are JSON `{"detail": "..."}`: 400 bad model id, 404 unknown thread, 409 a reply is
already streaming in that thread, 503 no model available.

`ModelInfo = {id: "<provider>:<name>", provider, name, thinking, detail}`. Providers:
`ollama`, `openai`, `anthropic`, and `fake` (offline demo).

## Messages

A `ChatMessage` is one turn: `{id, role: "user" | "assistant", created_at, status, parts}`.
`status` is `complete`, `stopped` or `error` (`streaming` exists only in the browser).
Parts appear in the order they happened:

```jsonc
{ "type": "text", "text": "..." }
{ "type": "reasoning", "text": "..." }          // the model's thinking
{ "type": "tool", "tool_call_id": "call_1", "name": "writer", "args": {...},
  "result": "..." | null, "status": "running" | "success" | "error",
  "agent": "writer" | null,                    // set for subagents
  "parts": [ /* the subagent's own parts, nested to any depth */ ] }
```

One assistant turn holds everything the graph produced for one user message: supervisor
text, every tool call and its result, and the final answer.

## Run events

`POST /api/threads/{id}/runs` starts a reply and streams it as Server-Sent Events. Each
event has `event: <type>` and `data: <json>`; the JSON repeats `type`.

The reply runs on the server, not in the request: closing the connection (switching chats,
reloading, closing the tab) only stops watching, and the reply still finishes and is saved.
`GET …/runs/live` re-attaches: it replays every event of the running reply from
`run_start`, then continues live (`running: true` on the thread says when to call it).
`POST …/runs/stop` stops the reply: the text so far is kept as a `stopped` message, any
unfinished tool call gets an error result so the thread stays valid, and the stream ends
with `done` / `stopped`. Delete also stops a running reply.

Events that come from inside the graph say where they came from:

- `ns`: the node path, outermost first. `[]` is the top-level graph,
  `["tools", "writer"]` is the `writer` node of a subgraph running inside `tools`.
- `parent_tool_call_id`: `null` for the supervisor's own output, otherwise the tool call
  whose subagent produced this event. Nest the event under that tool call.

| type | fields | meaning |
| --- | --- | --- |
| `run_start` | `protocol, run_id, thread_id, model, thinking` | always first |
| `user_message` | `message: ChatMessage` | the saved user turn (server id and time) |
| `step_start` | `step_id, node, ns, parent_tool_call_id` | a node started |
| `step_end` | `step_id, node, ns, parent_tool_call_id, error` | it finished |
| `text` | `message_id, node, agent, delta, ns, parent_tool_call_id` | answer tokens |
| `reasoning` | same as `text` | thinking tokens |
| `tool_call` | `tool_call_id, name, args, message_id, node, ns, parent_tool_call_id` | complete arguments, once per id |
| `tool_result` | `tool_call_id, name, content, status, ns, parent_tool_call_id` | once per id |
| `interrupt` | `value` | the graph called `interrupt()` (not supported by the UI yet) |
| `title` | `title` | the chat got its generated title (first turn only) |
| `error` | `message` | the graph raised; `done` follows |
| `done` | `status: complete \| error \| stopped` | always last |

Consecutive `text` deltas with the same `message_id` belong to one message; a new
`message_id` starts a new text part.

### Example: supervisor delegates to a subagent

```text
run_start        {model: "ollama:qwen3:8b", ...}
user_message     {message: {role: "user", parts: [{type: "text", text: "Write a haiku"}]}}
step_start       {node: "supervisor", ns: []}
text             {delta: "I'll ask the writer.", parent_tool_call_id: null}
tool_call        {tool_call_id: "call_1", name: "writer", args: {task: "..."}}
step_end         {node: "supervisor", ns: []}
step_start       {node: "tools", ns: []}
step_start       {node: "writer", ns: ["tools"]}
text             {delta: "Leaves", agent: "writer", ns: ["tools"], parent_tool_call_id: "call_1"}
...
tool_result      {tool_call_id: "call_1", content: "Leaves fall...", status: "success"}
step_start       {node: "supervisor", ns: []}
text             {delta: "Here it is:", parent_tool_call_id: null}
title            {title: "Haiku about autumn"}
done             {status: "complete"}
```

## How the backend produces it

`graph.astream(input, config, stream_mode=["messages", "updates", "tasks"],
subgraphs=True, version="v2")`, translated by `backend/app/streaming.py`:
`messages` → `text`/`reasoning`, `updates` → `tool_call`/`tool_result`,
`tasks` → `step_start`/`step_end`. Reasoning is read from LangChain's standard
`content_blocks`, so it works the same for Ollama, OpenAI and Anthropic.
