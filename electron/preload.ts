// Electron preload script — exposes a safe IPC bridge to the renderer.
// Runs in a separate context from the renderer; the renderer only sees window.electron.

import { contextBridge, ipcRenderer } from "electron";
import type { NovaStoreData } from "./types";

// ---------------------------------------------------------------------------
// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object.
// ---------------------------------------------------------------------------

contextBridge.exposeInMainWorld("electron", {
  // ── Theme ────────────────────────────────────────────────────────────────
  getTheme: () => ipcRenderer.invoke("get-theme"),
  setTheme: (theme: "light" | "dark" | "system") =>
    ipcRenderer.invoke("set-theme", theme),

  // ── Speech ──────────────────────────────────────────────────────────────
  getSpeechEnabled: () => ipcRenderer.invoke("get-speech-enabled"),
  setSpeechEnabled: (enabled: boolean) =>
    ipcRenderer.invoke("set-speech-enabled", enabled),

  // ── Nova API ────────────────────────────────────────────────────────────
  novaChat: (message: string, context?: string) =>
    ipcRenderer.invoke("nova-chat", message, context),

  novaState: () => ipcRenderer.invoke("nova-state"),

  novaScreen: () => ipcRenderer.invoke("nova-screen"),

  novaCommand: (action: string, params?: Record<string, unknown>) =>
    ipcRenderer.invoke("nova-command", action, params),

  novaHealth: () => ipcRenderer.invoke("nova-health"),

  // ── Store ───────────────────────────────────────────────────────────────
  getStore: () => ipcRenderer.invoke("get-store"),

  setStore: (key: keyof NovaStoreData, value: unknown) =>
    ipcRenderer.invoke("set-store", key, value),

  // ── Misc ────────────────────────────────────────────────────────────────
  getVersion: () => ipcRenderer.invoke("get-version"),

  getConfig: () => ipcRenderer.invoke("get-config"),

  showOpenDialog: (options: Electron.OpenDialogOptions) =>
    ipcRenderer.invoke("show-open-dialog", options),

  showSaveDialog: (options: Electron.SaveDialogOptions) =>
    ipcRenderer.invoke("show-save-dialog", options),

  openExternal: (url: string) => ipcRenderer.invoke("open-external", url),

  // ── App events (one-shot listener registration) ─────────────────────────
  onAutoStartChat: (cb: (msg: string) => void) => {
    const listener = (_e: Electron.IpcRendererEvent, msg: string) => cb(msg);
    ipcRenderer.on("auto-start-chat", listener);
    // Return a cleanup function
    return () => ipcRenderer.removeListener("auto-start-chat", listener);
  },

  onThemeChange: (cb: (theme: "light" | "dark") => void) => {
    const listener = (_e: Electron.IpcRendererEvent, theme: "light" | "dark") => cb(theme);
    ipcRenderer.on("theme-change", listener);
    return () => ipcRenderer.removeListener("theme-change", listener);
  },
});

// ---------------------------------------------------------------------------
// Log that preload loaded (helps debug if window.electron is undefined)
// ---------------------------------------------------------------------------
console.log("[preload] loaded — window.electron exposed");
