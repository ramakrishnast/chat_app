import { useState } from "react";

import { useChat } from "./chat/useChat";
import { Composer } from "./components/Composer";
import { MessageList } from "./components/MessageList";
import { ModelPicker } from "./components/ModelPicker";
import { Sidebar } from "./components/Sidebar";

export default function App() {
  const chat = useChat();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const activeTitle = chat.threads.find((t) => t.id === chat.activeId)?.title;
  const empty = chat.messages.length === 0 && !chat.loading;

  return (
    <div className="app">
      <Sidebar
        conversations={chat.threads}
        activeId={chat.activeId}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onSelect={(id) => {
          chat.selectThread(id);
          setSidebarOpen(false);
        }}
        onRename={chat.renameThread}
        onDelete={chat.deleteThread}
      />

      <main className="main">
        <header className="topbar">
          <button
            className="icon-button menu-button"
            aria-label="Open sidebar"
            onClick={() => setSidebarOpen(true)}
          >
            ☰
          </button>
          <ModelPicker
            models={chat.models}
            value={chat.model}
            thinking={chat.thinking}
            disabled={chat.streaming}
            onChange={chat.chooseModel}
            onThinkingChange={chat.toggleThinking}
            onRefresh={chat.reloadModels}
          />
          <span className="topbar-title">{activeTitle}</span>
        </header>

        {chat.error && (
          <div className="banner" role="alert">
            <span>{chat.error}</span>
            <button className="icon-button" aria-label="Dismiss" onClick={chat.dismissError}>
              ✕
            </button>
          </div>
        )}

        {empty ? (
          <div className="empty">
            <h1>How can I help?</h1>
            <p>{chat.model ? `Your agent is using ${chat.model}.` : "Pick a model to start."}</p>
          </div>
        ) : (
          <MessageList messages={chat.messages} />
        )}

        <Composer
          key={chat.activeId ?? "new"}
          streaming={chat.streaming}
          disabled={!chat.model}
          onSend={chat.send}
          onStop={chat.stop}
        />
      </main>
    </div>
  );
}
