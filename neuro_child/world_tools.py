"""
Browser tools with Playwright-backed headless Google search using dad's real Chrome profile/cache/cookies.
Falls back to Wikipedia when Playwright is unavailable.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any


class BrowserTools:
    def __init__(self, local: bool = True) -> None:
        self._local = local
        self._has_playwright = False
        self._has_browser_exec = False
        self._session = "nova-browser"
        self._chrome_profile = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Google"
            / "Chrome"
            / "User Data"
        )
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
            self._sync_playwright = sync_playwright
            self._has_playwright = True
        except Exception:
            self._sync_playwright = None  # type: ignore

    def _exec(self, code: str, *, local: Optional[bool] = None, session: Optional[str] = None) -> Dict[str, Any]:
        if not self._has_playwright:
            return {"error": "playwright not available", "result": ""}
        try:
            with self._sync_playwright().start() as p:
                profile = str(self._chrome_profile) if self._chrome_profile.exists() else None
                if profile:
                    context = p.chromium.launch_persistent_context(
                        profile,
                        headless=True,
                        args=["--profile-directory=Default"],
                    )
                else:
                    context = p.chromium.launch(headless=True).new_context()
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("about:blank", wait_until="domcontentloaded")
                result = eval(code, {"page": page, "context": context, "p": p, "browser": context.browser})
                try:
                    context.close()
                except Exception:
                    pass
                return {"result": str(result) if result is not None else ""}
        except Exception as e:
            return {"error": str(e), "result": ""}

    def search(self, query: str, engine: str = "google") -> str:
        if self._has_playwright:
            text = self._playwright_search(query, engine=engine)
            if text:
                return text
        text = self._wikipedia_search(query)
        if text:
            return text
        return "Search failed"

    def read_page(self, url: str) -> str:
        if self._has_playwright:
            return self._playwright_read(url)
        return self._http_get(url)

    def _playwright_search(self, query: str, engine: str = "google") -> str:
        try:
            with self._sync_playwright().start() as p:
                profile = str(self._chrome_profile) if self._chrome_profile.exists() else None
                if profile:
                    ctx = p.chromium.launch_persistent_context(
                        profile,
                        headless=True,
                        args=["--profile-directory=Default"],
                    )
                else:
                    ctx = p.chromium.launch(headless=True).new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                q = query.replace('"', '\\"')
                if engine == "duckduckgo":
                    page.goto(f"https://duckduckgo.com/?q={q}", wait_until="domcontentloaded", timeout=20000)
                else:
                    page.goto(f"https://www.google.com/search?q={q}", wait_until="domcontentloaded", timeout=20000)
                text = page.inner_text("body")
                try:
                    ctx.close()
                except Exception:
                    pass
                return re.sub(r"\s+", " ", text or "").strip()[:8000]
        except Exception:
            return ""

    def _playwright_read(self, url: str, visible: bool = False) -> str:
        try:
            with self._sync_playwright().start() as p:
                profile = str(self._chrome_profile) if self._chrome_profile.exists() else None
                if profile:
                    ctx = p.chromium.launch_persistent_context(
                        profile,
                        headless=not visible,
                        args=["--profile-directory=Default"],
                    )
                else:
                    ctx = p.chromium.launch(headless=not visible).new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                text = page.inner_text("body")
                try:
                    ctx.close()
                except Exception:
                    pass
                return re.sub(r"\s+", " ", text or "").strip()[:12000]
        except Exception as e:
            return f"ERROR: {e}"

    def open_visible(self, url: str) -> str:
        if not self._has_playwright:
            return "playwright not available"
        try:
            with self._sync_playwright().start() as p:
                profile = str(self._chrome_profile) if self._chrome_profile.exists() else None
                if profile:
                    ctx = p.chromium.launch_persistent_context(
                        profile,
                        headless=False,
                        args=["--profile-directory=Default"],
                    )
                else:
                    ctx = p.chromium.launch(headless=False).new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                return f"Opened: {url}"
        except Exception as e:
            return f"ERROR: {e}"

    def _wikipedia_search(self, query: str) -> str:
        try:
            import urllib.request, urllib.parse, ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            url = "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=" + urllib.parse.quote_plus(query) + "&format=json&srlimit=5"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            titles = [item.get("title", "") for item in data.get("query", {}).get("search", [])]
            if not titles:
                return ""
            read_url = "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=true&explaintext=true&titles=" + urllib.parse.quote_plus("|".join(titles[:2])) + "&format=json"
            req = urllib.request.Request(read_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            pages = data.get("query", {}).get("pages", {})
            texts = []
            for page in pages.values():
                extract = page.get("extract", "")
                if extract:
                    texts.append(extract)
            text = "\n\n".join(texts)
            return re.sub(r"\s+", " ", text or "").strip()[:8000]
        except Exception:
            return ""

    def _http_get(self, url: str, max_chars: int = 5000) -> str:
        try:
            import urllib.request, ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = resp.read(max_chars * 4)
            text = data.decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
        except Exception as e:
            return f"ERROR: {e}"


class FileTools:
    def read(self, path: str, max_chars: int = 5000) -> str:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
            return re.sub(r"\s+", " ", text or "").strip()[:max_chars]
        except Exception as e:
            return f"ERROR: {e}"

    def exists(self, path: str) -> bool:
        return Path(path).exists()


class WindowTools:
    def focus(self, title: str) -> str:
        try:
            import pyautogui
            wins = [w for w in pyautogui.getWindowsWithTitle(title) if title.lower() in w.title.lower()]
            if not wins:
                return f"No window matching '{title}'"
            wins[0].activate()
            return f"Focused: {wins[0].title}"
        except Exception as e:
            return f"ERROR: {e}"

