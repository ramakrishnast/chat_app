/**
 * The backend contract (protocol 1). This file and src/api/ are the only places that know
 * the wire format; components work with these types. Spec: docs/stream-contract.md.
 */

export const PROTOCOL_VERSION = 1;

// ------------------------------------------------------------------ REST shapes

export interface ModelInfo {
  id: string; // "<provider>:<name>", e.g. "ollama:qwen3:0.6b"
  provider: string;
  name: string;
  thinking: boolean; // whether the Think switch affects this model
  detail: string | null;
}

export interface ModelList {
  models: ModelInfo[];
  default: string | null;
}

export interface Thread {
  id: string;
  title: string;
  model: string | null;
  thinking: boolean;
  created_at: string;
  updated_at: string;
}

export interface TextPart {
  type: "text";
  text: string;
  message_id?: string | null;
}

export interface ReasoningPart {
  type: "reasoning";
  text: string;
  message_id?: string | null;
}

export interface ToolPart {
  type: "tool";
  tool_call_id: string;
  name: string;
  args: Record<string, unknown>;
  result: string | null;
  status: "running" | "success" | "error";
  agent?: string | null; // set when a subagent worked on this call
  parts: Part[]; // the subagent's own text, reasoning and tool calls
}

export type Part = TextPart | ReasoningPart | ToolPart;

export type MessageStatus = "complete" | "streaming" | "stopped" | "error";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  created_at: string | null;
  status: MessageStatus;
  parts: Part[];
}

export interface ThreadDetail extends Thread {
  messages: ChatMessage[];
  running: boolean; // a reply is being generated right now (re-attach with watchRun)
}

export interface RunRequest {
  content: string;
  model?: string | null;
  thinking?: boolean;
}

// ------------------------------------------------------------------ stream events

interface Located {
  ns: string[]; // node path, outermost first; [] is the top-level graph
  parent_tool_call_id: string | null; // set when the event belongs to a subagent's work
}

export type StreamEvent =
  | {
      type: "run_start";
      protocol: number;
      run_id: string;
      thread_id: string;
      model: string;
      thinking: boolean;
    }
  | { type: "user_message"; message: ChatMessage }
  | ({ type: "step_start"; step_id: string; node: string } & Located)
  | ({ type: "step_end"; step_id: string; node: string; error: string | null } & Located)
  | ({
      type: "text" | "reasoning";
      message_id: string | null;
      node: string | null;
      agent: string | null;
      delta: string;
    } & Located)
  | ({
      type: "tool_call";
      tool_call_id: string;
      name: string;
      args: Record<string, unknown>;
      message_id: string | null;
      node: string;
    } & Located)
  | ({
      type: "tool_result";
      tool_call_id: string;
      name: string | null;
      content: string;
      status: "success" | "error";
    } & Located)
  | { type: "interrupt"; value: string }
  | { type: "title"; title: string }
  | { type: "error"; message: string }
  | { type: "done"; status: "complete" | "error" | "stopped" };
