// Nova Electron renderer — root App component
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ChatPanel } from "@components/ChatPanel";
import { NovaPanel } from "@components/NovaPanel";
import { SettingsPanel } from "@components/SettingsPanel";
import { DriveBar, MoodBadge, KnowledgeList } from "@components/UI";
import { NovaChatReply, NovaState } from "@/types";

// ---------------------------------------------------------------------------
// Nova App — main layout
// ---------------------------------------------------------------------------
export default function App() {
  const [activeTab, setActiveTab] = useState<"chat" | "nova" | "settings">("chat");
  const [messages, setMessages] = useState<
    { role: "user" | "nova" | "system"; text: string; timestamp?: number }[]
  >([]);
  const [isLoading, setIsLoading] = useState(false);
  const [novaState, setNovaState] = useState<NovaState | null>(null);
  const [speechEnabled, setSpeechEnabled] = useState(true);
  const [theme, setTheme] = useState<"light" | "dark" | "system">("system");
  const [serverDown, setServerDown] = useState(false);
  const pollRef = useRef<number | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // ── Init: load theme + store + initial state ──────────────────────────────
  useEffect(() => {
    async function init() {
      try {
        const t = await window.electron.getTheme();
        setTheme(t);
        const store = await window.electron.getStore();
        setSpeechEnabled(store.speechEnabled);
        // Initial auth + health check
        const health = await window.electron.novaHealth();
        if (health.status === "down") {
          setServerDown(true);
          addSystemMessage("Nova server is offline — check that nova_server.py is running.");
        } else {
          // Fetch initial state
          const st = await window.electron.novaState();
          setNovaState(st);
          if (store.autoStartChat && store.lastChatMessage) {
            handleSend(store.lastChatMessage);
          }
        }
      } catch (e) {
        addSystemMessage("Failed to connect to Nova: " + (e as Error).message);
        setServerDown(true);
      }
    }
    init();
  }, []);

  // ── Theme sync ────────────────────────────────────────────────────────────
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme === "system" ? "system" : theme);
  }, [theme]);

  useEffect(() => {
    const unsub = window.electron.onThemeChange((newTheme) => {
      if (newTheme === "system") {
        const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        setTheme(isDark ? "system" : "light");
      } else {
        setTheme(newTheme);
      }
    });
    return unsub;
  }, []);

  // ── Auto-start chat listener ──────────────────────────────────────────────
  useEffect(() => {
    const unsub = window.electron.onAutoStartChat((msg) => {
      handleSend(msg);
    });
    return unsub;
  }, []);

  // ── Poll Nova state ──────────────────────────────────────────────────────
  useEffect(() => {
    async function poll() {
      try {
        const st = await window.electron.novaState();
        setNovaState(st);
        setServerDown(false);
      } catch {
        // Silent — health check handles outages
      }
    }
    poll();
    pollRef.current = window.setInterval(poll, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // ── Scroll chat to bottom ────────────────────────────────────────────────
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);

  // ── Send message ─────────────────────────────────────────────────────────
  const handleSend = useCallback(
    async (msg: string) => {
      if (!msg.trim() || isLoading) return;
      const trimmed = msg.trim();
      setMessages((prev) => [...prev, { role: "user", text: trimmed, timestamp: Date.now() }]);
      setMessages((prev) => [...prev, { role: "system", text: "…" }]);
      setIsLoading(true);

      try {
        const reply: NovaChatReply = await window.electron.novaChat(trimmed);
        // Remove the "…" placeholder
        setMessages((prev) => prev.slice(0, -1));

        if (reply.error) {
          setMessages((prev) => [
            ...prev,
            { role: "system", text: "Error: " + reply.error },
          ]);
          setServerDown(true);
          return;
        }

        setMessages((prev) => [
          ...prev,
          {
            role: "nova",
            text: reply.reply,
            timestamp: Date.now(),
          },
        ]);

        // Update state from reply
        if (reply.mood || reply.drives) {
          setNovaState((prev) => ({
            ...prev!,
            mood: reply.mood ?? prev?.mood ?? null,
            drives: reply.drives ?? prev?.drives ?? [],
          }));
        }

        // Play audio if present
        if (reply.audio && speechEnabled) {
          try {
            const audio = new Audio(reply.audio);
            audio.play().catch(() => {
              // Autoplay blocked — not a fatal error
            });
          } catch {
            // ignore
          }
        }

        setServerDown(false);
      } catch (e) {
        setMessages((prev) => prev.slice(0, -1));
        setMessages((prev) => [
          ...prev,
          { role: "system", text: "Connection error: " + (e as Error).message },
        ]);
        setServerDown(true);
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading, speechEnabled],
  );

  const addSystemMessage = (text: string) => {
    setMessages((prev) => [...prev, { role: "system", text }]);
  };

  // ── Settings changes ─────────────────────────────────────────────────────
  const handleSpeechToggle = useCallback(
    async (enabled: boolean) => {
      setSpeechEnabled(enabled);
      await window.electron.setSpeechEnabled(enabled);
    },
    [],
  );

  const handleThemeChange = useCallback(
    async (newTheme: "light" | "dark" | "system") => {
      setTheme(newTheme);
      await window.electron.setTheme(newTheme);
    },
    [],
  );

  // ── Layout ───────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen flex-col bg-bg text-fg">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg-elevated)] shrink-0">
        <div className="flex items-center gap-3">
          <div className="avatar w-8 h-8 text-xs" style={{ backgroundColor: "oklch(0.65 0.15 280)" }}>
            N
          </div>
          <div>
            <div className="text-sm font-semibold text-[var(--color-fg)]">Nova</div>
            <div className="text-[10px] text-[var(--color-fg-subtle)] flex items-center gap-1">
              {serverDown ? (
                <span className="inline-flex items-center gap-1 text-error">
                  <span className="w-1.5 h-1.5 rounded-full bg-error inline-block animate-pulse" />
                  offline
                </span>
              ) : (
                <span className="text-success">
                  <span className="w-1.5 h-1.5 rounded-full bg-success inline-block" />
                  online
                </span>
              )}
              <span className="mx-1">·</span>
              <span className="text-[10px]">v1.0</span>
            </div>
          </div>
        </div>

        <nav className="flex items-center gap-1">
          {(["chat", "nova", "settings"] as const).map((tab) => (
            <button
              key={tab}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                activeTab === tab
                  ? "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]"
                  : "text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-[var(--color-bg-muted)]"
              }`}
              onClick={() => setActiveTab(tab)}
            >
              {tab === "chat" ? "Chat" : tab === "nova" ? "Nova" : "Settings"}
            </button>
          ))}
        </nav>
      </header>

      {/* Main content */}
      <main className="flex-1 flex overflow-hidden">
        {activeTab === "chat" && (
          <ChatPanel
            messages={messages}
            onSend={handleSend}
            isLoading={isLoading}
          />
        )}

        {activeTab === "nova" && <NovaPanel state={novaState} />}

        {activeTab === "settings" && (
          <SettingsPanel
            theme={theme}
            onThemeChange={handleThemeChange}
            speechEnabled={speechEnabled}
            onSpeechToggle={handleSpeechToggle}
          />
        )}
      </main>
    </div>
  );
}
