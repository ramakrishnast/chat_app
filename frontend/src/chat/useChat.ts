import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api as defaultApi, type ChatApi } from "../api/client";
import type { ChatMessage, ModelInfo, StreamEvent, Thread } from "../contract";
import { applyEvent, type LiveMessage } from "./reduce";

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

/** A reply being shown for one chat. The reply itself runs on the server, so switching chats,
 * reloading or closing the tab doesn't stop it; this is only the browser's view of it. */
interface LiveRun {
  controller: AbortController;
  user: ChatMessage;
  reply: LiveMessage;
  finished: boolean;
}

export function useChat(api: ChatApi = defaultApi) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(idFromUrl);
  const [history, setHistory] = useState<LiveMessage[]>([]); // saved turns of the open chat
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [thinking, setThinking] = useState(() => stored(THINK_KEY) === "true");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Live runs by thread id. A ref, so background streams never read stale state; `version`
  // re-renders when one changes.
  const runs = useRef(new Map<string, LiveRun>());
  const [version, setVersion] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);

  const activeIdRef = useRef(activeId);
  const skipLoadRef = useRef<string | null>(null);
  const bump = useCallback(() => setVersion((v) => v + 1), []);

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
            "No models available. Start Ollama and pull a model (ollama pull qwen3:8b), " +
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

  // Back/forward switch chats. Replies keep streaming in the background.
  useEffect(() => {
    const onPop = () => {
      const id = idFromUrl();
      activeIdRef.current = id;
      setActiveId(id);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  /** Show a reply's events in `run` until its stream ends, then reload the saved turns. */
  const follow = useCallback(
    async (
      threadId: string,
      run: LiveRun,
      open: (signal: AbortSignal, onEvent: (event: StreamEvent) => void) => Promise<unknown>,
    ) => {
      try {
        await open(run.controller.signal, (event) => {
          if (event.type === "user_message") {
            run.user = event.message;
            // Re-attaching: the saved turns may already start this turn; the live copy wins.
            if (activeIdRef.current === threadId) {
              setHistory((list) => {
                const index = list.findIndex((m) => m.id === event.message.id);
                return index >= 0 ? list.slice(0, index) : list;
              });
            }
          } else if (event.type === "title") {
            setThreads((list) =>
              list.map((t) => (t.id === threadId ? { ...t, title: event.title } : t)),
            );
          } else {
            if (event.type === "error" && activeIdRef.current === threadId) {
              setError(event.message);
            }
            run.reply = applyEvent(run.reply, event);
          }
          bump();
        });
      } catch (e) {
        if (run.controller.signal.aborted) return; // the chat was deleted
        // Only the connection broke; the reply goes on on the server, and reopening the chat
        // re-attaches to it.
        if (activeIdRef.current === threadId) setError(`Lost the live view: ${errorText(e)}`);
      } finally {
        run.finished = true;
        bump();
        void refreshThreads();
        // Swap the live copy for the saved turns (now if the chat is open, else on next open).
        if (runs.current.get(threadId) === run && activeIdRef.current === threadId) {
          setReloadKey((k) => k + 1);
        }
      }
    },
    [bump, refreshThreads],
  );

  /** Show the reply already running in a chat that was just opened. */
  const attach = useCallback(
    (threadId: string) => {
      const run: LiveRun = {
        controller: new AbortController(),
        finished: false,
        user: {
          id: `live-user-${threadId}`,
          role: "user",
          created_at: null,
          status: "complete",
          parts: [],
        },
        reply: {
          id: `live-reply-${threadId}`,
          role: "assistant",
          created_at: now(),
          status: "streaming",
          parts: [],
          step: null,
        },
      };
      runs.current.set(threadId, run);
      bump();
      void follow(threadId, run, (signal, onEvent) => api.watchRun(threadId, signal, onEvent));
    },
    [api, bump, follow],
  );

  // Load the open chat's saved turns (again after one of its replies finishes).
  useEffect(() => {
    if (!activeId) {
      setHistory([]);
      return;
    }
    if (skipLoadRef.current === activeId) {
      skipLoadRef.current = null; // just created here: nothing saved yet
      setHistory([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .thread(activeId)
      .then((detail) => {
        if (cancelled) return;
        setHistory(detail.messages);
        if (detail.model) setModel(detail.model);
        setThinking(detail.thinking);
        // A finished reply is in the saved turns now; drop its live copy.
        const local = runs.current.get(activeId);
        if (local?.finished) {
          runs.current.delete(activeId);
          bump();
        }
        // A reply still running on the server (started in another tab, before a reload,
        // or the live view dropped): pick it up.
        if (detail.running && (!local || local.finished)) attach(activeId);
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
  }, [activeId, api, navigate, bump, attach, reloadKey]);

  const activeRun = activeId ? runs.current.get(activeId) : undefined;
  const streaming = Boolean(activeRun && !activeRun.finished);
  const messages = useMemo(
    () => (activeRun ? [...history, activeRun.user, activeRun.reply] : history),
    // `version` changes whenever a run is updated in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [history, activeRun, version],
  );

  const send = useCallback(
    async (text: string) => {
      const existing = activeIdRef.current ? runs.current.get(activeIdRef.current) : undefined;
      if ((existing && !existing.finished) || !model) return;
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
      const current = threadId;

      // A finished reply still shown live belongs in the history before the next turn.
      if (existing?.finished) {
        setHistory((list) => [...list, existing.user, existing.reply]);
      }
      const run: LiveRun = {
        controller: new AbortController(),
        finished: false,
        user: {
          id: `pending-user-${Date.now()}`,
          role: "user",
          created_at: now(),
          status: "complete",
          parts: [{ type: "text", text }],
        },
        reply: {
          id: `pending-reply-${Date.now()}`,
          role: "assistant",
          created_at: now(),
          status: "streaming",
          parts: [],
          model,
          step: null,
        },
      };
      runs.current.set(current, run);
      bump();

      await follow(current, run, (signal, onEvent) =>
        api.run(current, { content: text, model, thinking }, signal, onEvent),
      );
    },
    [api, model, navigate, thinking, bump, follow],
  );

  /** Stop the reply in the open chat (the user pressed ■). The server ends the stream with
   * done/stopped, which the live view shows like any other event. */
  const stop = useCallback(() => {
    const id = activeIdRef.current;
    if (id) void api.stopRun(id).catch((e: unknown) => setError(`Could not stop: ${errorText(e)}`));
  }, [api]);

  const selectThread = useCallback(
    (id: string | null) => {
      if (id === activeIdRef.current) return;
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
      try {
        await api.deleteThread(id); // also stops a reply running there
        runs.current.get(id)?.controller.abort();
        runs.current.delete(id);
        bump();
        setThreads((list) => list.filter((t) => t.id !== id));
        if (activeIdRef.current === id) navigate(null);
      } catch (e) {
        setError(`Could not delete: ${errorText(e)}`);
      }
    },
    [api, navigate, bump],
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
