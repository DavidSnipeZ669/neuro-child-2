// Electron-Vite config — merges the renderer Vite config with Electron main/preload builds.
import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: "dist-electron",
      rollupOptions: {
        input: { main: path.resolve(__dirname, "main.ts") },
        external: ["electron", "electron-log", "electron-store"],
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "electron"),
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: "dist-electron",
      rollupOptions: {
        input: { preload: path.resolve(__dirname, "preload.ts") },
        external: ["electron"],
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "electron"),
      },
    },
  },
  renderer: {
    plugins: [react(), tailwindcss()],
    root: path.resolve(__dirname, "renderer"),
    build: {
      outDir: "dist-renderer",
      emptyOutDir: true,
      rollupOptions: {
        input: path.resolve(__dirname, "renderer/index.html"),
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "renderer/src"),
        "@components": path.resolve(__dirname, "renderer/src/components"),
        "@hooks": path.resolve(__dirname, "renderer/src/hooks"),
        "@styles": path.resolve(__dirname, "renderer/styles"),
        "@assets": path.resolve(__dirname, "renderer/src/assets"),
      },
    },
    server: {
      port: 5173,
      strictPort: true,
      watch: {
        ignored: ["**/node_modules/**", "**/dist-*/**"],
      },
    },
    css: {
      devSourcemap: true,
    },
  },
});
