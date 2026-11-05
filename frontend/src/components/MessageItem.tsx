import { memo, useState } from "react";

import { answerText, type LiveMessage } from "../chat/reduce";
import { copyText } from "./copy";
import { Parts } from "./Parts";
import { Time } from "./Time";

function UserMessage({ message }: { message: LiveMessage }) {
  const text = message.parts.map((p) => (p.type === "text" ? p.text : "")).join("");
  return (
    <div className="message user">
      <div className="bubble">{text}</div>
      <div className="message-meta">
        <Time iso={message.created_at} />
      </div>
    </div>
  );
}

function AssistantMessage({ message }: { message: LiveMessage }) {
  const [copied, setCopied] = useState(false);
  const live = message.status === "streaming";
  const text = answerText(message);
  const waiting = live && message.parts.length === 0;

  const copy = async () => {
    if (await copyText(text)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div className="message assistant" aria-busy={live}>
      <Parts parts={message.parts} live={live} />
      {live && (
        <div className="progress" aria-live="polite">
          {waiting && (
            <span className="typing" aria-label="Waiting for reply">
              <span />
              <span />
              <span />
            </span>
          )}
          {message.step && <span className="step">Running {message.step}…</span>}
        </div>
      )}
      {message.status === "stopped" && <p className="note">Stopped.</p>}
      {message.status === "error" && (
        <p className="note error">{message.error ?? "The reply failed."}</p>
      )}
      {!live && (
        <div className="message-meta">
          <Time iso={message.created_at} />
          {text && (
            <button type="button" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </button>
          )}
          {message.model && <span className="model-tag">{message.model}</span>}
        </div>
      )}
    </div>
  );
}

export const MessageItem = memo(function MessageItem({ message }: { message: LiveMessage }) {
  return message.role === "user" ? (
    <UserMessage message={message} />
  ) : (
    <AssistantMessage message={message} />
  );
});
