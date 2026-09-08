// Renderer-only Vite config (ESM — handles @tailwindcss/vite which is ESM-only)
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  root: path.resolve(__dirname, "renderer"),
  base: "./",
  build: {
    outDir: "../dist-renderer",
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
});
