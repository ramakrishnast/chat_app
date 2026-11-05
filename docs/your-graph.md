# Plugging in your own graph

The backend runs whatever graph `GRAPH` points to. Start from
`backend/agents/example/graph.py` (a supervisor with two tools and a `writer` subagent).

## The shape: one node, one supervisor

```python
from langchain.agents import create_agent
from langgraph.graph import START, MessagesState, StateGraph
from agentkit import UseChatModel, default_model, subagent_tool

supervisor = create_agent(
    model=default_model(),              # placeholder; UseChatModel swaps in the UI's pick
    tools=[search, calculator, subagent_tool(researcher, name="researcher",
                                             description="...")],
    system_prompt="You coordinate tools and specialists...",
    middleware=[UseChatModel(), SummarizationMiddleware(...), ModelRetryMiddleware()],
    name="supervisor",
)

builder = StateGraph(MessagesState)
builder.add_node("supervisor", supervisor)
builder.add_edge(START, "supervisor")
```

Tools and middleware go on the supervisor; add more nodes to `builder` only when you need
steps around it. The app needs four things:

1. **State has `messages`** (`MessagesState` or a subclass). The app sends each user turn as
   `{"messages": [HumanMessage(...)]}` and keeps the history in the checkpointer per thread.
2. **`UseChatModel()` in every agent's middleware.** It runs each model call on the model
   picked in the UI (Ollama now; OpenAI/Anthropic once a key is set) with the Think switch
   applied. In a hand-written node, call `get_model(config)` instead.
3. **Subagents wrapped with `subagent_tool(...)`** (below), so their work shows under the
   tool call that started them.
4. **Export the uncompiled `builder`** or a compiled graph. The app compiles or copies it
   with its own Postgres checkpointer. A zero-argument factory (sync or async) also works.

## Subagents

Wrap a compiled subagent as a tool for the supervisor:

```python
from agentkit import subagent_tool

researcher = create_agent(model=default_model(), tools=[search_cases],
                          middleware=[UseChatModel()], name="researcher")
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
