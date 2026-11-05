import type { ModelList, RunRequest, StreamEvent, Thread, ThreadDetail } from "../contract";
import { parseSse } from "./sse";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail !== undefined) return JSON.stringify(body.detail);
  } catch {
    // not JSON
  }
  return `${response.status} ${response.statusText}`.trim();
}

/** Everything the UI needs from a backend. Swap the implementation to talk to another one. */
export interface ChatApi {
  models(refresh?: boolean): Promise<ModelList>;
  threads(): Promise<Thread[]>;
  thread(id: string): Promise<ThreadDetail>;
  createThread(body: { model: string | null; thinking: boolean }): Promise<Thread>;
  updateThread(
    id: string,
    changes: { title?: string; model?: string; thinking?: boolean },
  ): Promise<Thread>;
  deleteThread(id: string): Promise<void>;
  /** Start a reply and watch it until it ends. The reply runs on the server: aborting
   * `signal` only stops watching. Use stopRun to stop the reply itself. */
  run(
    threadId: string,
    body: RunRequest,
    signal: AbortSignal,
    onEvent: (event: StreamEvent) => void,
  ): Promise<void>;
  /** Re-attach to the reply running in a thread (events so far, then live).
   * Resolves false at once when nothing is running. */
  watchRun(
    threadId: string,
    signal: AbortSignal,
    onEvent: (event: StreamEvent) => void,
  ): Promise<boolean>;
  /** Stop the reply running in a thread; the text so far is kept. */
  stopRun(threadId: string): Promise<{ stopped: boolean }>;
}

export function createHttpApi(baseUrl = ""): ChatApi {
  const root = baseUrl.replace(/\/+$/, "");
  const headers = { "Content-Type": "application/json" };

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(root + path, { ...init, headers });
    if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  return {
    models: (refresh = false) => request(`/api/models${refresh ? "?refresh=true" : ""}`),
    threads: () => request("/api/threads"),
    thread: (id) => request(`/api/threads/${id}`),
    createThread: (body) => request("/api/threads", { method: "POST", body: JSON.stringify(body) }),
    updateThread: (id, changes) =>
      request(`/api/threads/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
    deleteThread: (id) => request(`/api/threads/${id}`, { method: "DELETE" }),
    async run(threadId, body, signal, onEvent) {
      const response = await fetch(`${root}/api/threads/${threadId}/runs`, {
        method: "POST",
        headers: { ...headers, Accept: "text/event-stream" },
        body: JSON.stringify(body),
        signal,
      });
      if (!response.ok || !response.body) {
        throw new ApiError(response.status, await errorDetail(response));
      }
      for await (const event of parseSse<StreamEvent>(response.body)) onEvent(event);
    },
    async watchRun(threadId, signal, onEvent) {
      const response = await fetch(`${root}/api/threads/${threadId}/runs/live`, {
        headers: { Accept: "text/event-stream" },
        signal,
      });
      if (response.status === 204) return false;
      if (!response.ok || !response.body) {
        throw new ApiError(response.status, await errorDetail(response));
      }
      for await (const event of parseSse<StreamEvent>(response.body)) onEvent(event);
      return true;
    },
    stopRun: (threadId) => request(`/api/threads/${threadId}/runs/stop`, { method: "POST" }),
  };
}

export const api: ChatApi = createHttpApi(import.meta.env.VITE_API_URL ?? "");
