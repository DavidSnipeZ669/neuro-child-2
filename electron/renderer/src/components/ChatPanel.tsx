import React, { useCallback, useEffect, useRef, useState } from "react";
import { NovaChatReply, NovaState, moodLabel, driveBar, pct, screenSrc, escapeHtml, truncate } from "@/types";

interface ChatBubbleProps {
  role: "user" | "nova" | "system";
  text: string;
  timestamp?: number;
}

function ChatBubble({ role, text, timestamp }: ChatBubbleProps) {
  const isUser = role === "user";
  const isSystem = role === "system";
  const bubbleClass = isSystem
    ? "chat-system"
    : isUser
      ? "chat-bubble-user"
      : "chat-bubble-nova";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div className={bubbleClass}>
        {isSystem ? (
          <span className="opacity-70">{escapeHtml(text)}</span>
        ) : (
          <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
            {escapeHtml(text)}
          </p>
        )}
        {timestamp != null && (
          <div className="text-[10px] opacity-40 mt-1 text-right select-none">
            {new Date(timestamp).toLocaleTimeString()}
          </div>
        )}
      </div>
    </div>
  );
}

interface ChatPanelProps {
  messages: { role: "user" | "nova" | "system"; text: string; timestamp?: number }[];
  onSend: (msg: string) => void;
  isLoading: boolean;
  onAttachment?: () => void;
}

export function ChatPanel({ messages, onSend, isLoading, onAttachment }: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [draft]);

  const send = useCallback(() => {
    const msg = draft.trim();
    if (!msg || isLoading) return;
    setDraft("");
    inputRef.current && (inputRef.current.style.height = "auto");
    onSend(msg);
  }, [draft, isLoading, onSend]);

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }, [send]);

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-3 py-3 space-y-1">
        {messages.length === 0 && (
          <div className="text-center text-[var(--color-fg-subtle)] mt-12 text-sm">
            Nova is loading… Say hello to get started.
          </div>
        )}
        {messages.map((m, i) => (
          <ChatBubble key={i} role={m.role} text={m.text} timestamp={m.timestamp} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-3 py-2 flex gap-2">
        {onAttachment && (
          <button
            className="btn-icon shrink-0"
            onClick={onAttachment}
            title="Attach file / link"
            type="button"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
          </button>
        )}
        <textarea
          ref={inputRef}
          className="textarea flex-1 min-h-[40px]"
          placeholder="Message Nova…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={isLoading}
          rows={1}
        />
        <button
          className="btn-primary shrink-0"
          onClick={send}
          disabled={!draft.trim() || isLoading}
          type="button"
        >
          {isLoading ? (
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------
// Drive bar component
// ------------------------------------------------------------------
interface DriveBarProps {
  name: string;
  level: number;       // 0..1 unmetness
  weight: number;
  description?: string;
}

function DriveBar({ name, level, weight, description }: DriveBarProps) {
  const barColor = level > 0.7
    ? "bg-error"
    : level > 0.5
      ? "bg-warning"
      : level > 0.3
        ? "bg-accent"
        : "bg-success";

  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2 mb-1">
          <span className="text-xs font-medium text-[var(--color-fg)] truncate">
            {escapeHtml(name)}
          </span>
          <span className="text-[10px] text-[var(--color-fg-subtle)] shrink-0">
            {pct(level)} · {driveBar(level)} urgency
          </span>
        </div>
        <div className="drive-bar">
          <div
            className={`drive-bar-fill ${barColor}`}
            style={{ width: `${pct(level)}` }}
          />
        </div>
        {description && (
          <div className="text-[10px] text-[var(--color-fg-subtle)] mt-0.5 truncate">
            {escapeHtml(description)}
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------
// Mood indicator
// ------------------------------------------------------------------
interface MoodBadgeProps {
  mood: NovaState["mood"];
}

function MoodBadge({ mood }: MoodBadgeProps) {
  if (!mood) return null;
  const label = moodLabel(mood);
  const hue = Math.round((mood.valence + 1) * 60); // 0..120 → red→yellow→green
  const color = `oklch(0.7 0.15 ${hue})`;

  return (
    <div className="flex items-center gap-2">
      <span className="mood-dot" style={{ backgroundColor: color }} />
      <span className="text-xs text-[var(--color-fg-muted)]">{label}</span>
      <span className="text-[10px] text-[var(--color-fg-subtle)]">
        {mood.valence >= 0 ? "+" : ""}{mood.valence.toFixed(2)}
      </span>
    </div>
  );
}

// ------------------------------------------------------------------
// Vocabulary / lessons list
// ------------------------------------------------------------------
interface KnowledgeListProps {
  title: string;
  items: { source: string; fact?: string; word?: string; meaning?: string }[];
}

function KnowledgeList({ title, items }: KnowledgeListProps) {
  if (!items.length) {
    return (
      <div className="text-xs text-[var(--color-fg-subtle)] italic py-2">
        Nothing learned yet — Nova picks things up as you talk.
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-fg-subtle)] mb-1">
        {title} ({items.length})
      </div>
      {items.slice(0, 20).map((item, i) => (
        <div key={i} className="text-xs text-[var(--color-fg-muted)] bg-[var(--color-bg-subtle)] rounded px-2 py-1">
          <span className="text-[var(--color-accent)] font-medium mr-1">
            {item.word ? escapeHtml(item.word) : escapeHtml(item.fact?.slice(0, 30) || "…")}
          </span>
          <span className="text-[var(--color-fg-subtle)]">
            {item.meaning ? escapeHtml(item.meaning) : item.fact ? escapeHtml(truncate(item.fact, 60)) : ""}
          </span>
          <span className="text-[10px] text-[var(--color-fg-subtle)] ml-auto shrink-0">
            {escapeHtml(truncate(item.source, 20))}
          </span>
        </div>
      ))}
      {items.length > 20 && (
        <div className="text-[10px] text-[var(--color-fg-subtle)] text-center pt-1">
          +{items.length - 20} more
        </div>
      )}
    </div>
  );
}

export { DriveBar, MoodBadge, KnowledgeList };
