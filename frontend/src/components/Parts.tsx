import { useState } from "react";

import type { Part, ReasoningPart, ToolPart } from "../contract";
import { Markdown } from "./Markdown";

function Reasoning({ part, live }: { part: ReasoningPart; live: boolean }) {
  return (
    <details className="thinking" open={live}>
      <summary>{live ? "Thinking…" : "Thought process"}</summary>
      <div className="thinking-body">{part.text}</div>
    </details>
  );
}

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args);
  if (entries.length === 1 && typeof entries[0]?.[1] === "string") return entries[0][1];
  return JSON.stringify(args, null, 2);
}

function Tool({ part, live }: { part: ToolPart; live: boolean }) {
  const [open, setOpen] = useState(false);
  const isAgent = Boolean(part.agent) || part.parts.length > 0;
  const running = part.status === "running";
  const icon = running ? "◌" : part.status === "error" ? "✕" : "✓";

  return (
    <div className={`tool-card ${part.status} ${isAgent ? "agent" : ""}`}>
      <button
        type="button"
        className="tool-header"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`tool-status ${running ? "spinning" : ""}`} aria-hidden="true">
          {icon}
        </span>
        <span className="tool-kind">{isAgent ? "Subagent" : "Tool"}</span>
        <span className="tool-name">{part.agent ?? part.name}</span>
        <span className="tool-chevron" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {/* A running subagent shows its work live even when collapsed. */}
      {(open || (running && isAgent && part.parts.length > 0)) && (
        <div className="tool-body">
          {open && (
            <section>
              <h4>{isAgent ? "Task" : "Input"}</h4>
              <pre>{formatArgs(part.args)}</pre>
            </section>
          )}
          {part.parts.length > 0 && (
            <section className="subagent-work">
              {open && <h4>Work</h4>}
              <Parts parts={part.parts} live={live && running} />
            </section>
          )}
          {open && part.result !== null && (
            <section>
              <h4>{part.status === "error" ? "Error" : "Result"}</h4>
              <pre>{part.result}</pre>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

/** A message's parts in arrival order: text, collapsible reasoning, tool / subagent cards. */
export function Parts({ parts, live }: { parts: Part[]; live: boolean }) {
  return (
    <>
      {parts.map((part, index) => {
        const last = index === parts.length - 1;
        if (part.type === "text") return <Markdown key={index} text={part.text} />;
        if (part.type === "reasoning") {
          return <Reasoning key={index} part={part} live={live && last} />;
        }
        return <Tool key={part.tool_call_id} part={part} live={live} />;
      })}
    </>
  );
}
