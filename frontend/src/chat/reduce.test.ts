import type { StreamEvent, ToolPart } from "../contract";
import { answerText, applyEvent, type LiveMessage } from "./reduce";

const at = { ns: [] as string[], parent_tool_call_id: null as string | null };

function text(delta: string, message_id = "m1", parent: string | null = null): StreamEvent {
  return {
    type: "text",
    delta,
    message_id,
    node: "supervisor",
    agent: parent ? "writer" : null,
    ...at,
    parent_tool_call_id: parent,
  };
}

function call(id: string, parent: string | null = null): StreamEvent {
  return {
    type: "tool_call",
    tool_call_id: id,
    name: "writer",
    args: { task: "x" },
    message_id: "m1",
    node: "supervisor",
    ...at,
    parent_tool_call_id: parent,
  };
}

const start: LiveMessage = {
  id: "r",
  role: "assistant",
  created_at: null,
  status: "streaming",
  parts: [],
};

const run = (...events: StreamEvent[]) => events.reduce(applyEvent, start);

test("tokens of one message merge; a new message id starts a new text part", () => {
  const m = run(text("Hel"), text("lo"), text("Bye", "m2"));
  expect(m.parts).toEqual([
    { type: "text", text: "Hello", message_id: "m1" },
    { type: "text", text: "Bye", message_id: "m2" },
  ]);
  expect(answerText(m)).toBe("Hello\n\nBye");
});

test("subagent output nests under its tool call, at any depth", () => {
  const m = run(
    text("Delegating."),
    call("c1"),
    text("draft", "s1", "c1"),
    call("c2", "c1"), // the subagent calls its own tool
    {
      type: "tool_result",
      tool_call_id: "c2",
      name: "count",
      content: "3",
      status: "success",
      ...at,
      ns: ["tools"],
      parent_tool_call_id: "c1",
    },
    {
      type: "tool_result",
      tool_call_id: "c1",
      name: "writer",
      content: "draft",
      status: "success",
      ...at,
    },
    text("Done.", "m2"),
  );
  const tool = m.parts[1] as ToolPart;
  expect(tool).toMatchObject({
    tool_call_id: "c1",
    agent: "writer",
    status: "success",
    result: "draft",
  });
  expect(tool.parts[0]).toMatchObject({ type: "text", text: "draft" });
  expect(tool.parts[1]).toMatchObject({ tool_call_id: "c2", status: "success", result: "3" });
  expect(answerText(m)).toBe("Delegating.\n\nDone.");
});

test("events for an unknown parent fall back to the top level; duplicates are ignored", () => {
  const m = run(text("orphan", "s1", "nope"), call("c1"), call("c1"));
  expect(m.parts.map((p) => p.type)).toEqual(["text", "tool"]);
});

test("stopping marks running tools as not finished", () => {
  const m = run(call("c1"), { type: "done", status: "stopped" });
  expect(m.status).toBe("stopped");
  expect((m.parts[0] as ToolPart).status).toBe("error");
});

test("an error event keeps the error status through done", () => {
  const m = run({ type: "error", message: "boom" }, { type: "done", status: "complete" });
  expect(m).toMatchObject({ status: "error", error: "boom" });
});

test("top-level steps drive the progress label", () => {
  const step = { step_id: "1", node: "tools", ...at };
  const m = run({ type: "step_start", ...step });
  expect(m.step).toBe("tools");
  expect(applyEvent(m, { type: "step_end", ...step, error: null }).step).toBeNull();
  const nested = applyEvent(start, { type: "step_start", ...step, ns: ["tools"] });
  expect(nested.step).toBeUndefined();
});
