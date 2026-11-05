import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { LiveMessage } from "../chat/reduce";
import { MessageItem } from "./MessageItem";

const reply: LiveMessage = {
  id: "a1",
  role: "assistant",
  created_at: "2026-11-04T10:15:00Z",
  status: "complete",
  model: "ollama:qwen3:0.6b",
  parts: [
    { type: "reasoning", text: "Should delegate." },
    {
      type: "tool",
      tool_call_id: "c1",
      name: "writer",
      args: { task: "Write a haiku" },
      result: "Leaves fall softly down",
      status: "success",
      agent: "writer",
      parts: [{ type: "text", text: "Leaves fall softly down" }],
    },
    { type: "text", text: "Here is your **haiku**." },
  ],
};

test("renders reasoning, a collapsible subagent card, the answer and a timestamp", async () => {
  render(<MessageItem message={reply} />);
  expect(screen.getByText("Thought process")).toBeInTheDocument();
  expect(screen.getByText("haiku").tagName).toBe("STRONG");
  expect(screen.getByText("Subagent")).toBeInTheDocument();
  expect(screen.queryByText("Write a haiku")).not.toBeInTheDocument(); // collapsed

  await userEvent.click(screen.getByRole("button", { name: /writer/ }));
  expect(screen.getByText("Write a haiku")).toBeInTheDocument();
  expect(screen.getAllByText("Leaves fall softly down")).toHaveLength(2); // work + result

  expect(document.querySelector("time")?.getAttribute("datetime")).toBe(reply.created_at);
  expect(screen.getByText("ollama:qwen3:0.6b")).toBeInTheDocument();
});

test("a streaming reply shows the running step and the stopped note later", () => {
  const live: LiveMessage = { ...reply, status: "streaming", parts: [], step: "supervisor" };
  const { rerender } = render(<MessageItem message={live} />);
  expect(screen.getByText("Running supervisor…")).toBeInTheDocument();
  expect(screen.getByLabelText("Waiting for reply")).toBeInTheDocument();
  rerender(<MessageItem message={{ ...live, status: "stopped", step: null }} />);
  expect(screen.getByText("Stopped.")).toBeInTheDocument();
});

test("user messages show their text and time", () => {
  render(
    <MessageItem
      message={{
        id: "u1",
        role: "user",
        created_at: "2026-11-04T10:14:00Z",
        status: "complete",
        parts: [{ type: "text", text: "Write me a haiku" }],
      }}
    />,
  );
  expect(screen.getByText("Write me a haiku")).toBeInTheDocument();
  expect(document.querySelector("time")).not.toBeNull();
});
