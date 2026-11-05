/**
 * Pure state transitions: apply one stream event to the assistant message being built.
 * Subagent output (events with parent_tool_call_id) goes inside that tool call's part,
 * however deep the nesting.
 */
import type { ChatMessage, Part, StreamEvent, ToolPart } from "../contract";

export interface LiveMessage extends ChatMessage {
  model?: string | null;
  step?: string | null; // top-level node running right now
  error?: string | null;
}

/** Return `parts` with `fn` applied to the part list of tool `toolId` (or `parts` itself). */
function inContainer(parts: Part[], toolId: string | null, fn: (parts: Part[]) => Part[]): Part[] {
  if (toolId === null) return fn(parts);
  let found = false;
  const next = parts.map((part) => {
    if (found || part.type !== "tool") return part;
    if (part.tool_call_id === toolId) {
      found = true;
      return { ...part, parts: fn(part.parts) };
    }
    const inner = inContainer(part.parts, toolId, fn);
    if (inner !== part.parts) {
      found = true;
      return { ...part, parts: inner };
    }
    return part;
  });
  return found ? next : parts;
}

function hasTool(parts: Part[], toolId: string): boolean {
  return parts.some(
    (p) => p.type === "tool" && (p.tool_call_id === toolId || hasTool(p.parts, toolId)),
  );
}

function updateTool(parts: Part[], toolId: string, fn: (tool: ToolPart) => ToolPart): Part[] {
  return parts.map((part) => {
    if (part.type !== "tool") return part;
    if (part.tool_call_id === toolId) return fn(part);
    return { ...part, parts: updateTool(part.parts, toolId, fn) };
  });
}

function target(message: LiveMessage, parent: string | null): string | null {
  return parent !== null && hasTool(message.parts, parent) ? parent : null;
}

export function applyEvent(message: LiveMessage, event: StreamEvent): LiveMessage {
  switch (event.type) {
    case "run_start":
      return { ...message, model: event.model };

    case "text":
    case "reasoning": {
      const parent = target(message, event.parent_tool_call_id);
      const parts = inContainer(message.parts, parent, (list) => {
        const last = list[list.length - 1];
        if (last && last.type === event.type && last.message_id === event.message_id) {
          return [...list.slice(0, -1), { ...last, text: last.text + event.delta }];
        }
        return [...list, { type: event.type, text: event.delta, message_id: event.message_id }];
      });
      const withAgent =
        parent && event.agent
          ? updateTool(parts, parent, (tool) => ({ ...tool, agent: event.agent }))
          : parts;
      return { ...message, parts: withAgent };
    }

    case "tool_call": {
      if (hasTool(message.parts, event.tool_call_id)) return message;
      const tool: ToolPart = {
        type: "tool",
        tool_call_id: event.tool_call_id,
        name: event.name,
        args: event.args,
        result: null,
        status: "running",
        agent: null,
        parts: [],
      };
      const parent = target(message, event.parent_tool_call_id);
      return { ...message, parts: inContainer(message.parts, parent, (list) => [...list, tool]) };
    }

    case "tool_result":
      return {
        ...message,
        parts: updateTool(message.parts, event.tool_call_id, (tool) => ({
          ...tool,
          result: event.content,
          status: event.status,
        })),
      };

    case "step_start":
      return event.ns.length === 0 ? { ...message, step: event.node } : message;

    case "step_end":
      return event.ns.length === 0 && message.step === event.node
        ? { ...message, step: null }
        : message;

    case "interrupt":
      return {
        ...message,
        error: "The graph paused for human input, which this UI doesn't support yet.",
      };

    case "error":
      return { ...message, status: "error", error: event.message };

    case "done":
      return {
        ...message,
        step: null,
        status: event.status === "complete" && message.status === "error" ? "error" : event.status,
        parts: finishRunning(message.parts, event.status !== "complete"),
      };

    default:
      return message;
  }
}

/** When a run ends early, tools still "running" will never get a result. */
function finishRunning(parts: Part[], early: boolean): Part[] {
  if (!early) return parts;
  return parts.map((p) =>
    p.type === "tool"
      ? {
          ...p,
          status: p.status === "running" ? "error" : p.status,
          parts: finishRunning(p.parts, early),
        }
      : p,
  );
}

/** Text of the answer itself (top-level text parts), e.g. for the copy button. */
export function answerText(message: ChatMessage): string {
  return message.parts
    .filter((p) => p.type === "text")
    .map((p) => p.text)
    .join("\n\n");
}
