// Electron main process — manages windows, IPC, auto-launch, Tailscale status.
import { app, BrowserWindow, ipcMain, shell, dialog } from "electron";
import path from "path";
import log from "electron-log/main";

// Logging is ready to use immediately (electron-log default export is the logger)
log.transports.file.level = "info";
log.transports.console.level = "debug";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const CONFIG = {
  // Nova server — override via env or command line
  novaHost: process.env.NOVA_HOST || "127.0.0.1",
  novaPort: parseInt(process.env.NOVA_PORT || "8000", 10),
  novaApiKey: process.env.NOVA_API_KEY || "",
  // Whether to use Tailscale hostname if available
  useTailscale: process.env.NOVA_USE_TAILSCALE === "1",
  tailscaleHostname: process.env.NOVA_TAILSCALE_HOST || "",
  // Window
  windowWidth: 1200,
  windowHeight: 900,
  minWidth: 900,
  minHeight: 600,
  // Auto-launch
  autoLaunch: process.env.NOVA_AUTOLAUNCH === "1",
};

// Build the base URL for the Nova backend
function novaBaseUrl(): string {
  const host = CONFIG.useTailscale && CONFIG.tailscaleHostname
    ? CONFIG.tailscaleHostname
    : CONFIG.novaHost;
  return `http://${host}:${CONFIG.novaPort}`;
}

function apiUrl(path: string): string {
  return `${novaBaseUrl()}${path}`;
}

function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...options.headers as Record<string, string>,
  };
  if (CONFIG.novaApiKey) {
    headers["X-API-Key"] = CONFIG.novaApiKey;
  }
  return fetch(apiUrl(path), { ...options, headers });
}

// ---------------------------------------------------------------------------
// Store for persisting user preferences
// ---------------------------------------------------------------------------
import Store from "electron-store";
const store = new Store({
  name: "nova-preferences",
  defaults: {
    theme: "system", // "light" | "dark" | "system"
    speechEnabled: true,
    autoStartChat: false,
    lastChatMessage: "",
    windowBounds: { width: CONFIG.windowWidth, height: CONFIG.windowHeight },
  },
});

// ---------------------------------------------------------------------------
// Tailwind theme helper (reads store.theme, writes to renderer via IPC)
// ---------------------------------------------------------------------------
function activeTheme(): "light" | "dark" {
  const t = store.get("theme") as string;
  if (t === "light" || t === "dark") return t;
  return "system";
}

// ---------------------------------------------------------------------------
// Window management
// ---------------------------------------------------------------------------
let mainWindow: BrowserWindow | null = null;
let splashWindow: BrowserWindow | null = null;

function createSplashWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 480,
    height: 360,
    resizable: false,
    minimizable: false,
    maximizable: false,
    movable: true,
    show: false,
    backgroundColor: "#1a1a2e",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false, // electron-store needs this
    },
  });

  splashWindow = win;

  // Load a splash HTML page
  win.loadFile(path.join(__dirname, "../renderer/splash.html"));
  win.once("ready-to-show", () => win.show());

  return win;
}

function createMainWindow(): BrowserWindow {
  const bounds = store.get("windowBounds") as { width: number; height: number } | undefined;
  const win = new BrowserWindow({
    width: bounds?.width || CONFIG.windowWidth,
    height: bounds?.height || CONFIG.windowHeight,
    minWidth: CONFIG.minWidth,
    minHeight: CONFIG.minHeight,
    resizable: true,
    show: false,
    backgroundColor: "#0f0f1a",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
    icon: path.join(__dirname, "../assets/icon.png"),
  });

  mainWindow = win;

  // Load the React app (built by Vite into dist-renderer/)
  win.loadFile(path.join(__dirname, "../dist-renderer/index.html"));

  win.once("ready-to-show", () => {
    // Apply theme before showing
    applyTheme(win, activeTheme());
    win.show();
  });

  win.on("resize", () => {
    if (win.isMaximized()) return;
    const [w, h] = win.getSize();
    store.set("windowBounds", { width: w, height: h });
  });

  win.on("close", () => {
    if (win.isMaximized()) return;
    const [w, h] = win.getSize();
    store.set("windowBounds", { width: w, height: h });
  });

  // IPC handlers for the renderer
  setupIpcHandlers(win);

  return win;
}

// ---------------------------------------------------------------------------
// Theme application
// ---------------------------------------------------------------------------
function applyTheme(win: BrowserWindow, theme: string): void {
  // Pass the theme through to the renderer. For "system", the renderer
  // (which has window.matchMedia) resolves the actual preference.
  if (win.webContents) {
    win.webContents.send("theme-change", theme);
  }
}

// System theme changes are handled by the renderer (which has access to
// window.matchMedia). The main process just listens for the renderer's
// notification via IPC and applies the resolved theme.
// (See renderer/src/components/SettingsPanel.tsx or App.tsx for the
//  matchMedia listener that sends "system-theme-changed" to main.)

// ---------------------------------------------------------------------------
// IPC Handlers
// ---------------------------------------------------------------------------
function setupIpcHandlers(win: BrowserWindow): void {
  // --- Theme ---
  ipcMain.handle("get-theme", () => activeTheme());
  ipcMain.handle("set-theme", (_e, theme: string) => {
    store.set("theme", theme);
    applyTheme(win, theme);
    return activeTheme();
  });

  // --- Speech ---
  ipcMain.handle("get-speech-enabled", () => store.get("speechEnabled") as boolean);
  ipcMain.handle("set-speech-enabled", (_e, enabled: boolean) => {
    store.set("speechEnabled", enabled);
    return enabled;
  });

  // --- Nova API proxy ---
  ipcMain.handle("nova-chat", async (_e, message: string, context?: string) => {
    try {
      const res = await apiFetch("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message, context }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "unknown error" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (err) {
      log.error("nova-chat failed: %o", err);
      return { error: String(err) };
    }
  });

  ipcMain.handle("nova-state", async () => {
    try {
      const res = await apiFetch("/api/state");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      log.error("nova-state failed: %o", err);
      return { error: String(err) };
    }
  });

  ipcMain.handle("nova-screen", async () => {
    try {
      const res = await apiFetch("/api/screen");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      log.error("nova-screen failed: %o", err);
      return { error: String(err) };
    }
  });

  ipcMain.handle("nova-command", async (_e, action: string, params?: Record<string, unknown>) => {
    try {
      const res = await apiFetch("/api/command", {
        method: "POST",
        body: JSON.stringify({ action, params }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      log.error("nova-command failed: %o", err);
      return { error: String(err) };
    }
  });

  ipcMain.handle("nova-health", async () => {
    try {
      const res = await apiFetch("/health");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      return { status: "down", error: String(err) };
    }
  });

  // --- Dialogs ---
  ipcMain.handle("show-open-dialog", async (_e, options) => {
    const result = await dialog.showOpenDialog(win, options);
    return result;
  });

  ipcMain.handle("show-save-dialog", async (_e, options) => {
    const result = await dialog.showSaveDialog(win, options);
    return result;
  });

  // --- Shell ---
  ipcMain.handle("open-external", async (_e, url: string) => {
    await shell.openExternal(url);
    return true;
  });

  // --- Config ---
  ipcMain.handle("get-config", () => ({
    novaHost: CONFIG.novaHost,
    novaPort: CONFIG.novaPort,
    useTailscale: CONFIG.useTailscale,
    tailscaleHostname: CONFIG.tailscaleHostname,
    apiKeySet: Boolean(CONFIG.novaApiKey),
  }));

  ipcMain.handle("get-store", () => ({
    theme: store.get("theme"),
    speechEnabled: store.get("speechEnabled"),
    autoStartChat: store.get("autoStartChat"),
    lastChatMessage: store.get("lastChatMessage"),
    windowBounds: store.get("windowBounds"),
  }));

  ipcMain.handle("set-store", (_e, key: string, value: unknown) => {
    store.set(key, value);
    return true;
  });

  // --- Version ---
  ipcMain.handle("get-version", () => app.getVersion());

  log.info("IPC handlers registered");
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(async () => {
  log.info("Nova Electron app starting…");
  log.info("Nova backend: %s", novaBaseUrl());
  log.info("API key set: %s", CONFIG.novaApiKey ? "yes" : "no");

  // Splash screen while backend initializes
  const splash = createSplashWindow();

  // Give the backend a moment to start, then show main window
  await new Promise((r) => setTimeout(r, 1500));

  const win = createMainWindow();
  splash.close();

  // Auto-start a chat if configured
  if (store.get("autoStartChat") && CONFIG.novaApiKey) {
    // Send an initial message to wake Nova up
    const msg = store.get("lastChatMessage") || "hello dad";
    win.webContents.send("auto-start-chat", msg);
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  log.info("Nova Electron app quitting…");
});

// ---------------------------------------------------------------------------
// Export for tests
// ---------------------------------------------------------------------------
export { CONFIG, novaBaseUrl, apiFetch, store, mainWindow };
