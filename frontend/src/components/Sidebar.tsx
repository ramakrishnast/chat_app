import { useState, type KeyboardEvent } from "react";

import type { Thread } from "../contract";

interface Props {
  conversations: Thread[];
  activeId: string | null;
  open: boolean;
  onClose: () => void;
  onSelect: (id: string | null) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

const DAY = 24 * 60 * 60 * 1000;

function groupLabel(updatedAt: string, now: number): string {
  const age = now - new Date(updatedAt).getTime();
  if (age < DAY) return "Today";
  if (age < 2 * DAY) return "Yesterday";
  if (age < 7 * DAY) return "Previous 7 days";
  if (age < 30 * DAY) return "Previous 30 days";
  return "Older";
}

export function Sidebar({
  conversations,
  activeId,
  open,
  onClose,
  onSelect,
  onRename,
  onDelete,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const now = Date.now();
  const groups: { label: string; items: Thread[] }[] = [];
  for (const conversation of conversations) {
    const label = groupLabel(conversation.updated_at, now);
    const group = groups.find((g) => g.label === label);
    if (group) group.items.push(conversation);
    else groups.push({ label, items: [conversation] });
  }

  const commit = (id: string) => {
    const title = draft.trim();
    setEditingId(null);
    if (title) onRename(id, title);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>, id: string) => {
    if (event.key === "Enter") commit(id);
    if (event.key === "Escape") setEditingId(null);
  };

  return (
    <>
      <div className={`scrim ${open ? "visible" : ""}`} onClick={onClose} aria-hidden="true" />
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Chats">
        <button type="button" className="new-chat" onClick={() => onSelect(null)}>
          <span aria-hidden="true">＋</span> New chat
        </button>
        <nav className="conversation-list">
          {conversations.length === 0 && <p className="sidebar-empty">No chats yet.</p>}
          {groups.map((group) => (
            <section key={group.label}>
              <h2>{group.label}</h2>
              <ul>
                {group.items.map((c) => (
                  <li key={c.id} className={c.id === activeId ? "active" : ""}>
                    {editingId === c.id ? (
                      <input
                        aria-label="Conversation title"
                        value={draft}
                        autoFocus
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => onKeyDown(e, c.id)}
                        onBlur={() => commit(c.id)}
                      />
                    ) : (
                      <>
                        <button
                          type="button"
                          className="conversation"
                          title={c.title}
                          aria-current={c.id === activeId ? "page" : undefined}
                          onClick={() => onSelect(c.id)}
                        >
                          {c.title}
                        </button>
                        <span className="row-actions">
                          <button
                            type="button"
                            aria-label={`Rename ${c.title}`}
                            onClick={() => {
                              setDraft(c.title);
                              setEditingId(c.id);
                            }}
                          >
                            ✎
                          </button>
                          <button
                            type="button"
                            aria-label={`Delete ${c.title}`}
                            onClick={() => {
                              if (window.confirm(`Delete "${c.title}"? This can't be undone.`)) {
                                onDelete(c.id);
                              }
                            }}
                          >
                            🗑
                          </button>
                        </span>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </nav>
      </aside>
    </>
  );
}
