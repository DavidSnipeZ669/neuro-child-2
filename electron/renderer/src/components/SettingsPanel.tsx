import React, { useState } from "react";
import { NovaState } from "@/types";

// ---------------------------------------------------------------------------
// SettingsPanel — theme switching (light/dark/system), speech toggle, about
// ---------------------------------------------------------------------------
interface SettingsPanelProps {
  theme: "light" | "dark" | "system";
  onThemeChange: (theme: "light" | "dark" | "system") => void;
  speechEnabled: boolean;
  onSpeechToggle: (enabled: boolean) => void;
}

function ThemeCard({
  theme,
  onThemeChange,
}: {
  theme: "light" | "dark" | "system";
  onThemeChange: (t: "light" | "dark" | "system") => void;
}) {
  return (
    <div className="card">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-subtle)] mb-3">
        Theme
      </h3>
      <div className="flex gap-2">
        {(
          [
            { value: "light" as const, label: "Light", icon: "☀️" },
            { value: "dark" as const, label: "Dark", icon: "🌙" },
            { value: "system" as const, label: "System", icon: "💻" },
          ] as const
        ).map((opt) => (
          <button
            key={opt.value}
            className={`flex-1 flex flex-col items-center gap-1 py-3 px-2 rounded-lg border transition-all ${
              theme === opt.value
                ? "border-[var(--color-accent)] bg-[var(--color-accent-muted)] text-[var(--color-accent)]"
                : "border-[var(--color-border)] bg-[var(--color-bg-elevated)] text-[var(--color-fg-muted)] hover:border-[var(--color-accent)]"
            }`}
            onClick={() => onThemeChange(opt.value)}
          >
            <span className="text-xl">{opt.icon}</span>
            <span className="text-xs font-medium">{opt.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function SpeechCard({
  enabled,
  onToggle,
}: {
  enabled: boolean;
  onToggle: (v: boolean) => void;
}) {
  return (
    <div className="card">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-subtle)] mb-3">
        Speech
      </h3>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm text-[var(--color-fg)]">Text-to-speech</div>
          <div className="text-xs text-[var(--color-fg-subtle)]">
            Nova reads her replies aloud using edge-tts.
          </div>
        </div>
        <button
          className={`relative w-12 h-6 rounded-full transition-colors ${
            enabled ? "bg-accent" : "bg-[var(--color-bg-subtle)]"
          }`}
          onClick={() => onToggle(!enabled)}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
              enabled ? "translate-x-6" : ""
            }`}
          />
        </button>
      </div>
    </div>
  );
}

function AboutCard() {
  return (
    <div className="card">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-subtle)] mb-3">
        About
      </h3>
      <div className="space-y-2 text-sm text-[var(--color-fg-muted)]">
        <div>
          <span className="text-[var(--color-fg)] font-medium">Nova</span> — AI companion
        </div>
        <div className="text-xs">
          A local AI that sees your screen, learns from conversation,
          and controls your PC. Built with Python (backend) + Electron (frontend).
        </div>
        <div className="pt-2 border-t border-[var(--color-border)] text-[10px] text-[var(--color-fg-subtle)]">
          Nova is a simulated companion — she behaves as though she has drives,
          moods, and goals, but this is a behavioural model, not a claim of
          sentience.
        </div>
      </div>
    </div>
  );
}

export function SettingsPanel({
  theme,
  onThemeChange,
  speechEnabled,
  onSpeechToggle,
}: SettingsPanelProps) {
  return (
    <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-4">
      <ThemeCard theme={theme} onThemeChange={onThemeChange} />
      <SpeechCard enabled={speechEnabled} onToggle={onSpeechToggle} />
      <AboutCard />
    </div>
  );
}
