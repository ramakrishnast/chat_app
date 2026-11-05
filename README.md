# Agent Chat

A ChatGPT-style chat UI for **your LangGraph agents**. You write the graph (a supervisor with
tools and subagents); the app streams it to the browser token by token, shows every tool
call and subagent as it works, and keeps each conversation in a LangGraph checkpointer.

- Streams `graph.astream(...)`: answer tokens, model thinking, node steps, tool calls and
  results, and subagents nested under the tool call that started them
- Any model per chat: **Ollama** locally today; **OpenAI** and **Anthropic** appear as soon
  as their API keys are set. A Think switch turns on reasoning for models that support it
- Plain chat: question and answer with timestamps, sidebar with auto titles grouped by
  date, rename/delete, stop mid-reply (the partial answer is kept)
- Frontend and backend are decoupled: the UI depends only on a documented
  [stream contract](docs/stream-contract.md), and the backend runs any graph named by
  `GRAPH=module:attr`

```
Browser: React + Vite (TypeScript)   frontend/
   │  REST + Server-Sent Events (docs/stream-contract.md)
   ▼
FastAPI   backend/app/        loads GRAPH, translates astream() into events
   │
   ├─► your graph            backend/agents/… (or GRAPH_PYTHONPATH)
   │      └─ agentkit.get_model(config) ─► Ollama | OpenAI | Anthropic
   ▼
Postgres 16: LangGraph checkpoints (the conversations) + chat list
```

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 20+, Docker (for Postgres), and
[Ollama](https://ollama.com) with a model that supports tools, e.g. `ollama pull qwen3:8b`.

```bash
make setup      # .env from .env.example, Python + npm dependencies
make db-up      # Postgres in Docker
make dev        # API on :8000, UI on http://localhost:5173
```

No Ollama yet? `make demo` runs everything with an offline demo model and in-memory storage.
Try "Write a poem about rivers" (supervisor → writer subagent) or "What is 17 * 23?"
(calculator tool).

## Plugging in your graph

Point `GRAPH` in `.env` at it. The full guide is [docs/your-graph.md](docs/your-graph.md);
in short: a `messages` state, the LLM from `get_model(config)`, `config` passed along, and
subagents wrapped with `subagent_tool(...)`.

```python
from agentkit import get_model, subagent_tool

async def supervisor(state: MessagesState, config: RunnableConfig) -> dict:
    reply = await get_model(config).bind_tools(TOOLS).ainvoke(state["messages"], config)
    return {"messages": [reply]}
```

## Models and keys

| Provider | Enable with | Model ids |
| --- | --- | --- |
| Ollama | running Ollama (`OLLAMA_BASE_URL`) | every installed chat model, `ollama:<name>` |
| OpenAI | `OPENAI_API_KEY` (+ `OPENAI_BASE_URL` for compatible servers) | `OPENAI_MODELS`, `openai:<name>` |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODELS`, `anthropic:<name>` |

Keys stay on the server; the browser only sees model ids. Think maps to Ollama
`reasoning`, OpenAI `reasoning.effort`, and Anthropic extended thinking
(`ANTHROPIC_THINKING_BUDGET`). `DEFAULT_MODEL` picks the model for new chats.

## Commands

Run `make` to list them: `dev`, `demo`, `test`, `lint`, `format`, `db-up`, `db-down`.

## Configuration

All settings live in `.env`; see `.env.example` for every option. The important ones:
`GRAPH`, `GRAPH_PYTHONPATH`, `DATABASE_URL` (empty = in memory), the model keys above, and
`CORS_ORIGINS` (where the UI is served from). The UI reads `VITE_API_URL`
(`frontend/.env.example`) when it is not served next to the API.

## Layout

```
backend/
  agentkit/          get_model(config), subagent_tool(...)  ← import these in your graph
  agents/example/    example supervisor + tools + writer subagent
  app/
    main.py          FastAPI app, REST routes, lifespan (checkpointer, store, graph)
    runs.py          one turn: astream → SSE, stop/err handling
    streaming.py     astream parts → contract events (attribution of subagent output)
    history.py       checkpointer state → chat messages with timestamps
    llm.py           model catalog + builders for Ollama/OpenAI/Anthropic
    graph_loader.py  GRAPH=module:attr → compiled graph with the checkpointer
    store.py         chat list (Postgres or memory)
  tests/             pytest: full runs with a scripted model, stop, history, loader
frontend/src/
  contract.ts        the wire types (only api/ and these types know the protocol)
  api/               REST client + SSE parser
  chat/              reducer (events → message tree) and the useChat hook
  components/        Sidebar, MessageList, MessageItem, Parts (tool/subagent cards), …
docs/                stream contract, plugging in your graph
```
