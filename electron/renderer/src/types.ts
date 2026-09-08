/// <reference lib="dom" />
/// <reference types="vite/client" />
import type { Store } from "electron-store";
import type { BrowserWindow } from "electron";

// ---------------------------------------------------------------------------
// Tier-1 types (no library imports beyond DOM + tsc builtins)
// ---------------------------------------------------------------------------

// Nova backend API shapes (mirror api/types.py / nova_server.py)
export interface NovaMood {
  valence: number;   // -1..1
  arousal: number;   // 0..1
  dominance: number; // 0..1
  label?: string;
}

export interface NovaDrive {
  name: string;
  level: number;       // 0..1 — how unmet the drive is (higher = more urgent)
  weight: number;      // priority weight
  description?: string;
}

export interface NovaState {
  mood: NovaMood | null;
  drives: NovaDrive[];
  thoughts: string[];
  goals: string[];
  lessons: { source: string; fact: string }[];
  vocabulary: { word: string; meaning: string; source: string }[];
  screen: string | null;   // base64 PNG
  speaking: boolean;
  listening: boolean;
  timestamp: number;
  error?: string;
}

export interface NovaChatReply {
  reply: string;
  audio?: string;         // data:audio/mp3;base64,...
  thinking?: string;
  mood?: NovaMood;
  drives?: NovaDrive[];
}

export interface NovaHealth {
  status: "ok" | "down";
  backend_started?: boolean;
  error?: string;
}

export interface NovaConfig {
  novaHost: string;
  novaPort: number;
  useTailscale: boolean;
  tailscaleHostname: string;
  apiKeySet: boolean;
}

export interface NovaStoreData {
  theme: "light" | "dark" | "system";
  speechEnabled: boolean;
  autoStartChat: boolean;
  lastChatMessage: string;
  windowBounds: { width: number; height: number };
}

// ---------------------------------------------------------------------------
// IPC bridge — the only place the renderer talks to the main process
// ---------------------------------------------------------------------------

declare global {
  interface Window {
    electron: {
      // Theme
      getTheme: () => Promise<"light" | "dark">;
      setTheme: (theme: "light" | "dark" | "system") => Promise<"light" | "dark">;
      // Speech
      getSpeechEnabled: () => Promise<boolean>;
      setSpeechEnabled: (enabled: boolean) => Promise<boolean>;
      // Nova API
      novaChat: (message: string, context?: string) => Promise<NovaChatReply>;
      novaState: () => Promise<NovaState>;
      novaScreen: () => Promise<{ image?: string; timestamp?: number; error?: string }>;
      novaCommand: (action: string, params?: Record<string, unknown>) => Promise<{ status?: string; result?: string; error?: string }>;
      novaHealth: () => Promise<NovaHealth>;
      // Store
      getStore: () => Promise<NovaStoreData>;
      setStore: (key: keyof NovaStoreData, value: unknown) => Promise<boolean>;
      // Misc
      getVersion: () => Promise<string>;
      getConfig: () => Promise<NovaConfig>;
      showOpenDialog: (options: any) => Promise<any>;
      showSaveDialog: (options: any) => Promise<any>;
      openExternal: (url: string) => Promise<boolean>;
      // App events
      onAutoStartChat: (cb: (msg: string) => void) => void;
      onThemeChange: (cb: (theme: "light" | "dark") => void) => void;
    };
  }
}

// ---------------------------------------------------------------------------
// Tier-2 helpers (pure functions, no Electron dependency)
// ---------------------------------------------------------------------------

/** Format a Nova timestamp for display */
export function formatTimestamp(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Format a mood label if available, else derive from valence */
export function moodLabel(mood: NovaMood | null | undefined): string {
  if (!mood) return "—";
  if (mood.label) return mood.label;
  const v = mood.valence;
  if (v > 0.5) return "happy";
  if (v > 0.1) return "content";
  if (v > -0.1) return "neutral";
  if (v > -0.5) return "low";
  return "sad";
}

/** Format drive level as a bar label */
export function driveBar(level: number): string {
  if (level < 0.2) return "calm";
  if (level < 0.4) return "mild";
  if (level < 0.6) return "active";
  if (level < 0.8) return "urgent";
  return "critical";
}

/** Clamp a 0..1 value to a percentage string */
export function pct(v: number): string {
  return Math.round(Math.max(0, Math.min(1, v)) * 100) + "%";
}

/** Escape HTML to prevent XSS from backend strings */
export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Truncate a string to maxLen, appending "…" if truncated */
export function truncate(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen - 1) + "…";
}

/** Format a base64 data URL as an <img> src, or return a placeholder */
export function screenSrc(data: string | null | undefined): string {
  if (!data) return "";
  if (data.startsWith("data:image/")) return data;
  // Fallback: maybe it's raw base64
  return `data:image/png;base64,${data}`;
}

/** Convert a base64 audio data URL to an Audio element src */
export function audioSrc(data?: string): string | null {
  if (!data) return null;
  if (data.startsWith("data:audio/")) return data;
  return null;
}

/** Generate a stable seed from a string for avatars */
export function avatarSeed(name: string): number {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash) + name.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

/** Interpolate a CSS colour between two hex values by t in 0..1 */
export function lerpColour(a: string, b: string, t: number): string {
  const pa = hexToRgb(a);
  const pb = hexToRgb(b);
  if (!pa || !pb) return a;
  const r = Math.round(pa.r + (pb.r - pa.r) * t);
  const g = Math.round(pa.g + (pb.g - pa.g) * t);
  const bl = Math.round(pa.b + (pb.b - pa.b) * t);
  return `#${r.toString(16).padStart(2,"0")}${g.toString(16).padStart(2,"0")}${bl.toString(16).padStart(2,"0")}`;
}

function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const m = hex.match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
  if (!m) return null;
  return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) };
}

// ---------------------------------------------------------------------------
// Types-only exports (consumed by components)
// ---------------------------------------------------------------------------
export type {
  NovaMood,
  NovaDrive,
  NovaState,
  NovaChatReply,
  NovaHealth,
  NovaConfig,
  NovaStoreData,
};
