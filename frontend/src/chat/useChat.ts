import { useCallback, useEffect, useRef, useState } from "react";

import { api as defaultApi, type ChatApi } from "../api/client";
import type { ChatMessage, ModelInfo, Thread } from "../contract";
import { applyEvent, type LiveMessage } from "./reduce";

const PENDING_USER = "pending-user";
const PENDING_REPLY = "pending-reply";
const MODEL_KEY = "chat.model";
const THINK_KEY = "chat.thinking";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function idFromUrl(): string | null {
  return /^#\/c\/([0-9a-f-]{36})$/i.exec(window.location.hash)?.[1] ?? null;
}

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // storage disabled: the choice just isn't remembered
  }
}

const now = () => new Date().toISOString();

export function useChat(api: ChatApi = defaultApi) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(idFromUrl);
  const [messages, setMessages] = useState<LiveMessage[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [thinking, setThinking] = useState(() => stored(THINK_KEY) === "true");
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeIdRef = useRef(activeId);
  const abortRef = useRef<AbortController | null>(null);
  const streamThreadRef = useRef<string | null>(null);
  const skipLoadRef = useRef<string | null>(null);

  const navigate = useCallback((id: string | null) => {
    const url = id ? `#/c/${id}` : window.location.pathname + window.location.search;
    window.history.pushState(null, "", url);
    activeIdRef.current = id;
    setActiveId(id);
  }, []);

  const refreshThreads = useCallback(async () => {
    try {
      setThreads(await api.threads());
    } catch (e) {
      setError(`Could not load chats: ${errorText(e)}`);
    }
  }, [api]);

  const loadModels = useCallback(
    async (refresh = false) => {
      try {
        const list = await api.models(refresh);
        setModels(list.models);
        const ids = new Set(list.models.map((m) => m.id));
        setModel((current) => {
          if (current && ids.has(current)) return current;
          const saved = stored(MODEL_KEY);
          if (saved && ids.has(saved)) return saved;
          return list.default;
        });
        if (list.models.length === 0) {
          setError(
            "No models available. Start Ollama and pull a model (ollama pull qwen3:0.6b), " +
              "or set OPENAI_API_KEY / ANTHROPIC_API_KEY, then press ↻.",
          );
        }
      } catch (e) {
        setError(`Can't reach the backend: ${errorText(e)}`);
      }
    },
    [api],
  );

  useEffect(() => {
    void refreshThreads();
    void loadModels();
  }, [refreshThreads, loadModels]);

  // Back/forward switch chats; leaving a streaming chat stops its reply.
  useEffect(() => {
    const onPop = () => {
      const id = idFromUrl();
      if (id !== streamThreadRef.current) abortRef.current?.abort();
      activeIdRef.current = id;
      setActiveId(id);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    if (skipLoadRef.current === activeId) {
      skipLoadRef.current = null; // just created here; messages are already in state
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .thread(activeId)
      .then((detail) => {
        if (cancelled) return;
        setMessages(detail.messages);
        if (detail.model) setModel(detail.model);
        setThinking(detail.thinking);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(`Could not open chat: ${errorText(e)}`);
        navigate(null);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [activeId, api, navigate]);

  const send = useCallback(
    async (text: string) => {
      if (streaming || !model) return;
      setError(null);
      let threadId = activeIdRef.current;
      try {
        if (!threadId) {
          const thread = await api.createThread({ model, thinking });
          threadId = thread.id;
          setThreads((list) => [thread, ...list]);
          skipLoadRef.current = threadId;
          navigate(threadId);
        }
      } catch (e) {
        setError(`Could not start a chat: ${errorText(e)}`);
        return;
      }

      const user: ChatMessage = {
        id: PENDING_USER,
        role: "user",
        created_at: now(),
        status: "complete",
        parts: [{ type: "text", text }],
      };
      const reply: LiveMessage = {
        id: PENDING_REPLY,
        role: "assistant",
        created_at: now(),
        status: "streaming",
        parts: [],
        model,
        step: null,
      };
      setMessages((list) => [...list, user, reply]);

      const controller = new AbortController();
      abortRef.current = controller;
      streamThreadRef.current = threadId;
      setStreaming(true);
      const current = threadId;
      const update = (fn: (m: LiveMessage) => LiveMessage) => {
        if (activeIdRef.current !== current) return; // the user moved to another chat
        setMessages((list) => list.map((m) => (m.id === PENDING_REPLY ? fn(m) : m)));
      };

      try {
        await api.run(current, { content: text, model, thinking }, controller.signal, (event) => {
          if (event.type === "user_message") {
            setMessages((list) => list.map((m) => (m.id === PENDING_USER ? event.message : m)));
          } else if (event.type === "title") {
            setThreads((list) =>
              list.map((t) => (t.id === current ? { ...t, title: event.title } : t)),
            );
          } else {
            if (event.type === "error") setError(event.message);
            update((m) => applyEvent(m, event));
          }
        });
      } catch (e) {
        if (controller.signal.aborted) {
          update((m) => applyEvent(m, { type: "done", status: "stopped" }));
        } else {
          setError(errorText(e));
          update((m) => applyEvent(m, { type: "done", status: "error" }));
        }
      } finally {
        abortRef.current = null;
        streamThreadRef.current = null;
        setStreaming(false);
        // Give the reply a stable id so a later event can't touch it.
        setMessages((list) =>
          list.map((m) => (m.id === PENDING_REPLY ? { ...m, id: `reply-${Date.now()}` } : m)),
        );
        void refreshThreads();
      }
    },
    [api, model, navigate, refreshThreads, streaming, thinking],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const selectThread = useCallback(
    (id: string | null) => {
      if (id === activeIdRef.current) return;
      abortRef.current?.abort();
      setError(null);
      navigate(id);
    },
    [navigate],
  );

  const chooseModel = useCallback(
    (id: string) => {
      setModel(id);
      remember(MODEL_KEY, id);
      const threadId = activeIdRef.current;
      if (threadId) void api.updateThread(threadId, { model: id }).catch(() => undefined);
    },
    [api],
  );

  const toggleThinking = useCallback(
    (value: boolean) => {
      setThinking(value);
      remember(THINK_KEY, String(value));
      const threadId = activeIdRef.current;
      if (threadId) void api.updateThread(threadId, { thinking: value }).catch(() => undefined);
    },
    [api],
  );

  const renameThread = useCallback(
    async (id: string, title: string) => {
      try {
        const thread = await api.updateThread(id, { title });
        setThreads((list) => list.map((t) => (t.id === id ? thread : t)));
      } catch (e) {
        setError(`Could not rename: ${errorText(e)}`);
      }
    },
    [api],
  );

  const deleteThread = useCallback(
    async (id: string) => {
      if (id === streamThreadRef.current) abortRef.current?.abort();
      try {
        await api.deleteThread(id);
        setThreads((list) => list.filter((t) => t.id !== id));
        if (activeIdRef.current === id) navigate(null);
      } catch (e) {
        setError(`Could not delete: ${errorText(e)}`);
      }
    },
    [api, navigate],
  );

  return {
    threads,
    activeId,
    messages,
    models,
    model,
    thinking,
    streaming,
    loading,
    error,
    send,
    stop,
    selectThread,
    chooseModel,
    toggleThinking,
    renameThread,
    deleteThread,
    reloadModels: () => loadModels(true),
    dismissError: () => setError(null),
  };
}
