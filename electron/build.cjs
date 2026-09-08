// build.cjs — Nova Electron production build
// 1. esbuild for main.ts + preload.ts (CJS, survives)
// 2. Vite CLI for renderer (handles ESM @tailwindcss/vite natively)
"use strict";
const esbuild = require("esbuild");
const path = require("path");
const fs = require("fs");
const { execSync } = require("child_process");

const distElectron = path.resolve(__dirname, "dist-electron");
const distRenderer = path.resolve(__dirname, "dist-renderer");
const nodeBin = process.execPath;

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

async function buildEsbuild(entry, outfile, externals) {
  console.log(`Building ${path.basename(outfile)} (esbuild)...`);
  const result = await esbuild.build({
    bundle: true,
    minify: true,
    sourcemap: false,
    format: "cjs",
    external: externals,
    entryPoints: [path.resolve(__dirname, entry)],
    outdir: distElectron,
    platform: "node",
    target: "node18",
    banner: { js: '"use strict";' },
  });
  console.log(`  -> ${path.relative(__dirname, outfile)}`);
}

function buildRenderer() {
  console.log("Building renderer (Vite CLI)...");
  // Call vite/bin/vite.js directly via node — avoids .cmd wrapper parse error
  const viteJs = path.resolve(__dirname, "node_modules", "vite", "bin", "vite.js");
  try {
    execSync(
      `"${nodeBin}" "${viteJs}" build --config vite.renderer.config.mjs --mode production`,
      { cwd: __dirname, stdio: "inherit", timeout: 120000 }
    );
  } catch (e) {
    console.error("Vite renderer build failed:", e.status || e.message);
    throw e;
  }
  console.log("  -> dist-renderer/");
}

async function run() {
  ensureDir(distElectron);
  ensureDir(distRenderer);

  try {
    await buildEsbuild("main.ts", path.join(distElectron, "main.js"), ["electron", "electron-log", "electron-store"]);
    await buildEsbuild("preload.ts", path.join(distElectron, "preload.js"), ["electron"]);
    buildRenderer();
    console.log("\nBUILD OK");
    console.log("  dist-electron/main.js");
    console.log("  dist-electron/preload.js");
    console.log("  dist-renderer/");
  } catch (e) {
    console.error("\nBUILD FAIL:", e?.message || e);
    process.exit(e?.status || e?.code || 1);
  }
}

run();
