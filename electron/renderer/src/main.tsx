// Nova Electron renderer — React entry point
import React from "react";
import ReactDOM from "react-dom/client";
import App from "@components/App";
import "@styles/tailwind.css";

// Apply theme on initial load (before React hydrates)
function applyInitialTheme() {
  const html = document.documentElement;
  // Check if already set (e.g. by main process)
  if (html.getAttribute("data-theme")) return;
  // Try to get stored preference
  const stored = localStorage.getItem("nova-theme");
  if (stored === "light" || stored === "dark") {
    html.setAttribute("data-theme", stored);
    return;
  }
  // Default to system
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  html.setAttribute("data-theme", prefersDark ? "dark" : "light");
}

applyInitialTheme();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
