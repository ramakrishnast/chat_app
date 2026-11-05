# Plugging in your own graph

The backend runs whatever graph `GRAPH` points to. Start from
`backend/agents/example/graph.py` (a supervisor with two tools and a `writer` subagent).

## The contract, in four rules

1. **State has `messages`.** Use `MessagesState` or a subclass. The app sends each user
   turn as `{"messages": [HumanMessage(...)]}` and keeps the history in the checkpointer
   per thread, so nodes see the whole conversation in `state["messages"]`. Extra state keys
   are fine.
2. **Get the LLM from `get_model(config)`**, never construct one in a node:

   ```python
   from agentkit import get_model

   async def supervisor(state: MessagesState, config: RunnableConfig) -> dict:
       model = get_model(config).bind_tools(TOOLS)
       reply = await model.ainvoke([SystemMessage(PROMPT), *state["messages"]], config)
       return {"messages": [reply]}
   ```

   That is the model picked in the UI (Ollama now; OpenAI/Anthropic once a key is set) with
   the Think switch applied. `get_model(config, thinking=False)` forces thinking off, e.g.
   for a quick routing call.
3. **Pass `config` along** to every model call and sub-graph (`ainvoke(..., config)`).
   That is what makes tokens stream and keeps subagents on the same model.
4. **Export the uncompiled builder** (`builder = StateGraph(...)`) or a compiled graph. The
   app compiles or copies it with its own Postgres checkpointer. A zero-argument factory
   (sync or async) also works, e.g. `GRAPH=my_agents.legal:make_graph`.

## Subagents

Wrap a compiled subagent as a tool for the supervisor:

```python
from agentkit import subagent_tool

researcher = research_builder.compile(name="researcher")
TOOLS = [
    search_cases,
    subagent_tool(researcher, name="researcher",
                  description="Research a legal question in the case corpus."),
]
```

The subagent gets the task as a fresh conversation and runs with the caller's config.
The UI shows its tokens, thinking and tool calls live inside the supervisor's tool card,
and they are still there after a reload (its transcript is stored as the tool message's
artifact). A subgraph you invoke yourself inside a plain tool also streams; with several
calls running in parallel, `subagent_tool` is what keeps each one under the right card.

A compiled agent added directly as a node (`builder.add_node("agent", create_agent(...))`)
also works: its output is treated as the main answer.

## Keeping your graph in its own repo

```bash
GRAPH_PYTHONPATH=/path/to/my-agents      # put on sys.path before importing
GRAPH=legal_rag.graph:builder
```

When the app loads your graph, `agentkit` is already importable. To run the graph on its
own (tests, notebooks), put this repo's `backend/` on `PYTHONPATH` too, since
`get_model` uses the backend's model registry and `.env`.

## Running it outside the app

The same graph works in a notebook or `langgraph dev`; pass the model yourself:

```python
graph.invoke({"messages": [("user", "hi")]},
             {"configurable": {"model": "ollama:qwen3:8b", "thinking": False}})
```

## Notes from adapting the legal RAG graph (chat_vanila_legal)

- Read the question from `state["messages"]`, not a separate `question` key, or follow-up
  questions lose their context.
- Run the ReAct agent as a subgraph/node (or via `subagent_tool`) with `config`, rather than
  a blocking `agent.invoke(...)` inside a node, so its tokens and tool calls stream.
- Drop prefixes such as `[Supervisor/Agent]` from message text: the UI already shows which
  node and subagent produced what.
- Human-in-the-loop `interrupt()` is reported to the UI but not resumable yet.
