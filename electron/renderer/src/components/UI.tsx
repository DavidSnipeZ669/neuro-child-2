import React from "react";
import { NovaState } from "@/types";

// ---------------------------------------------------------------------------
// MoodBadge — small coloured dot + label showing Nova's current mood
// ---------------------------------------------------------------------------
interface MoodBadgeProps {
  mood: NovaState["mood"];
}

export function MoodBadge({ mood }: MoodBadgeProps) {
  if (!mood) return null;
  // Derive a hue from valence: -1 → red, 0 → neutral gray, +1 → green
  const hue = Math.round(120 + mood.valence * 60); // 60..180 range (red→green)
  const saturation = mood.arousal * 40 + 20;       // 20..60%
  const lightness = 55 + mood.valence * 10;        // 45..65%

  const color = `hsl(${hue}, ${saturation}%, ${lightness}%)`;

  return (
    <div className="flex items-center gap-1.5">
      <span
        className="inline-block w-2.5 h-2.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      <span className="text-xs text-[var(--color-fg-muted)]">
        {mood.label || "neutral"}
      </span>
      {mood.valence !== undefined && (
        <span className="text-[10px] text-[var(--color-fg-subtle)]">
          {mood.valence >= 0 ? "+" : ""}
          {mood.valence.toFixed(2)}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DriveBar — horizontal urgency bar for a single drive
// ---------------------------------------------------------------------------
interface DriveBarProps {
  name: string;
  level: number;       // 0..1 unmetness
  weight: number;
  description?: string;
}

const URGENCY_COLORS: Record<string, string> = {
  calm: "bg-success",
  mild: "bg-info",
  active: "bg-accent",
  urgent: "bg-warning",
  critical: "bg-error",
};

function urgencyLabel(level: number): string {
  if (level < 0.2) return "calm";
  if (level < 0.4) return "mild";
  if (level < 0.6) return "active";
  if (level < 0.8) return "urgent";
  return "critical";
}

export function DriveBar({ name, level, weight, description }: DriveBarProps) {
  const urg = urgencyLabel(level);
  const barColor = URGENCY_COLORS[urg] ?? "bg-accent";
  const pct = Math.round(Math.max(0, Math.min(1, level)) * 100);

  return (
    <div className="flex items-start gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2 mb-1">
          <span className="text-sm font-medium text-[var(--color-fg)] truncate">
            {name}
          </span>
          <span className="text-[10px] text-[var(--color-fg-subtle)] shrink-0">
            {pct}% · {urg}
          </span>
        </div>
        <div className="h-2 w-full rounded-full bg-[var(--color-bg-subtle)] overflow-hidden">
          <div
            className={`h-full rounded-full ${barColor} transition-all duration-500`}
            style={{ width: `${pct}%` }}
          />
        </div>
        {description && (
          <div className="text-[11px] text-[var(--color-fg-subtle)] mt-1 truncate">
            {description}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KnowledgeList — shared component for lessons + vocabulary tables
// ---------------------------------------------------------------------------
interface KnowledgeItem {
  source: string;
  fact?: string;
  word?: string;
  meaning?: string;
}

interface KnowledgeListProps {
  title: string;
  items: KnowledgeItem[];
}

export function KnowledgeList({ title, items }: KnowledgeListProps) {
  if (!items?.length) {
    return (
      <div className="text-sm text-[var(--color-fg-subtle)] italic py-2">
        Nothing learned yet — Nova picks things up as you talk.
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-fg-subtle)] mb-1">
        {title} ({items.length})
      </div>
      {items.slice(0, 30).map((item, i) => (
        <div
          key={i}
          className="text-sm text-[var(--color-fg-muted)] bg-[var(--color-bg-subtle)] rounded px-3 py-2"
        >
          <span className="text-[var(--color-accent)] font-medium mr-1.5">
            {item.word || (item.fact ? item.fact.slice(0, 24) : "…")}
          </span>
          <span className="text-[var(--color-fg-subtle)]">
            {item.meaning || item.fact || ""}
          </span>
          <span className="text-[10px] text-[var(--color-fg-subtle)] ml-auto shrink-0">
            {item.source?.slice(0, 20)}
          </span>
        </div>
      ))}
      {items.length > 30 && (
        <div className="text-[10px] text-[var(--color-fg-subtle)] text-center pt-1">
          +{items.length - 30} more
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Re-export NovaState for consumers
// ---------------------------------------------------------------------------
export type { NovaState };
