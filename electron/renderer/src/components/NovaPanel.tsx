// Nova panel — shows Nova's inner state: mood, drives, goals, lessons, vocabulary
import React from "react";
import { NovaState } from "@/types";
import { MoodBadge, DriveBar, KnowledgeList } from "@/components/UI";

interface NovaPanelProps {
  state: NovaState | null;
}

export function NovaPanel({ state }: NovaPanelProps) {
  if (!state) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--color-fg-subtle)]">
        <div className="text-center">
          <div className="text-4xl mb-3 opacity-30">🤖</div>
          <div className="text-sm">Loading Nova's state…</div>
        </div>
      </div>
    );
  }

  if (state.error) {
    return (
      <div className="flex-1 flex items-center justify-center text-error">
        <div className="text-center">
          <div className="text-4xl mb-3">⚠️</div>
          <div className="text-sm">{state.error}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-4">
      {/* Mood + speaking status */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-subtle)]">
            Mood
          </h2>
          <MoodBadge mood={state.mood} />
        </div>
        <div className="flex items-center gap-4">
          {state.speaking && (
            <span className="inline-flex items-center gap-1.5 text-xs text-accent bg-accent-muted px-2 py-1 rounded-full">
              <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
              Speaking
            </span>
          )}
          {state.listening && (
            <span className="inline-flex items-center gap-1.5 text-xs text-info bg-info/20 px-2 py-1 rounded-full">
              <span className="w-2 h-2 rounded-full bg-info animate-pulse" />
              Listening
            </span>
          )}
          {!state.speaking && !state.listening && (
            <span className="text-xs text-[var(--color-fg-subtle)]">Idle</span>
          )}
        </div>
      </div>

      {/* Drives */}
      <div className="card">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-subtle)] mb-3">
          Drives
        </h2>
        <div className="space-y-2">
          {state.drives.map((d) => (
            <DriveBar key={d.name} name={d.name} level={d.level} weight={d.weight} description={d.description} />
          ))}
          {state.drives.length === 0 && (
            <div className="text-xs text-[var(--color-fg-subtle)] italic">No active drives</div>
          )}
        </div>
      </div>

      {/* Thoughts */}
      {state.thoughts && state.thoughts.length > 0 && (
        <div className="card">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-subtle)] mb-2">
            Thoughts
          </h2>
          <div className="space-y-1">
            {state.thoughts.map((t, i) => (
              <div key={i} className="text-sm text-[var(--color-fg)] bg-[var(--color-bg-subtle)] rounded px-3 py-2">
                {t}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Goals */}
      {state.goals && state.goals.length > 0 && (
        <div className="card">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-subtle)] mb-2">
            Goals
          </h2>
          <div className="space-y-1">
            {state.goals.map((g, i) => (
              <div key={i} className="flex items-start gap-2 text-sm">
                <span className="text-accent mt-0.5">●</span>
                <span className="text-[var(--color-fg)]">{g}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Lessons learned */}
      <KnowledgeList
        title="Lessons"
        items={state.lessons || []}
      />

      {/* Vocabulary */}
      <KnowledgeList
        title="Vocabulary"
        items={state.vocabulary || []}
      />

      {/* Screen capture (if available) */}
      {state.screen && (
        <div className="card">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-subtle)] mb-2">
            Screen
          </h2>
          <div className="rounded-lg border border-[var(--color-border)] overflow-hidden max-h-[300px]">
            <img
              src={state.screen}
              alt="Nova's current screen view"
              className="w-full h-auto max-h-[300px] object-contain bg-black"
            />
          </div>
          <div className="text-[10px] text-[var(--color-fg-subtle)] mt-1">
            {new Date(state.timestamp!).toLocaleTimeString()}
          </div>
        </div>
      )}

      {/* Live screen (if implemented via /api/screen) */}
    </div>
  );
}
