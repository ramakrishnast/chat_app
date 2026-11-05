import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

interface Props {
  streaming: boolean;
  disabled?: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

const MAX_HEIGHT = 240;

function fitHeight(el: HTMLTextAreaElement) {
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
}

export function Composer({ streaming, disabled = false, onSend, onStop }: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow with the content up to MAX_HEIGHT, then scroll.
  useLayoutEffect(() => {
    if (ref.current) fitHeight(ref.current);
  }, [text]);

  // Re-measure when the width changes (window resize, or first paint in a hidden/zero-width frame).
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth !== width) {
        width = el.clientWidth;
        fitHeight(el);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const submit = () => {
    const value = text.trim();
    if (!value || streaming || disabled) return;
    onSend(value);
    setText("");
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (streaming) onStop();
    else submit();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form className="composer" onSubmit={onSubmit}>
      <div className="composer-box">
        <textarea
          ref={ref}
          rows={1}
          value={text}
          autoFocus
          placeholder={disabled ? "Pick a model to start…" : "Message the agent…"}
          aria-label="Message"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {streaming ? (
          <button type="submit" className="send-button" aria-label="Stop generating">
            ■
          </button>
        ) : (
          <button
            type="submit"
            className="send-button"
            aria-label="Send message"
            disabled={!text.trim() || disabled}
          >
            ↑
          </button>
        )}
      </div>
      <p className="composer-hint">Enter to send · Shift+Enter for a new line</p>
    </form>
  );
}
