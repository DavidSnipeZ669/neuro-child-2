"""
World tools for Nova: file system, browser automation, window focus.
"""
from __future__ import annotations

import os
import re
import ssl
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class FileTools:
    """Create, read, edit, delete files and folders."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or Path.cwd()

    def list(self, path: str) -> List[str]:
        try:
            return [str(p) for p in Path(path).iterdir()]
        except Exception:
            return []

    def read(self, path: str, max_chars: int = 4000) -> str:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
            return text[:max_chars]
        except Exception as e:
            return f"ERROR: {e}"

    def write(self, path: str, content: str) -> str:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"wrote {p}"
        except Exception as e:
            return f"ERROR: {e}"

    def append(self, path: str, content: str) -> str:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
            return f"appended to {p}"
        except Exception as e:
            return f"ERROR: {e}"

    def delete(self, path: str) -> str:
        try:
            p = Path(path)
            if p.exists():
                p.unlink()
                return f"deleted {p}"
            return "missing"
        except Exception as e:
            return f"ERROR: {e}"

    def mkdir(self, path: str) -> str:
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            return f"mkdir {path}"
        except Exception as e:
            return f"ERROR: {e}"


class BrowserTools:
    """
    Browser automation using the user's actual Chromium profile/cookies/cache when available.
    Default mode: headless/local backend via browser_exec if present.
    Falls back to direct HTTP fetching if browser_exec is unavailable.
    Only opens visible browser when explicitly requested.
    """

    def __init__(self, local: bool = True, session: str = "nova_default") -> None:
        self._local = local
        self._session = session
        self._visible_session = "nova_visible"
        self._has_browser_exec = False
        try:
            import browser_exec  # noqa: F401
            self._has_browser_exec = True
        except Exception:
            self._has_browser_exec = False

    def _exec(self, code: str, *, local: Optional[bool] = None, session: Optional[str] = None) -> Dict[str, Any]:
        if not self._has_browser_exec:
            return {"error": "browser_exec not available", "result": ""}
        try:
            from browser_exec import browser_exec
            kw: Dict[str, Any] = {"code": code, "session": session or self._session}
            if local is None:
                kw["local"] = self._local
            else:
                kw["local"] = local
            return browser_exec(**kw)
        except Exception as e:
            return {"error": str(e), "result": ""}

    def _http_get(self, url: str, max_chars: int = 5000) -> str:
        try:
            import urllib.request
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            # Try to inject cookies from local Edge/Chrome if available
            try:
                cookie = self._load_browser_cookie_for_url(url)
                if cookie:
                    headers["Cookie"] = cookie
            except Exception:
                pass
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = resp.read(max_chars * 4)
            text = data.decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
        except Exception as e:
            return f"ERROR: {e}"

    def _load_browser_cookie_for_url(self, url: str) -> Optional[str]:
        try:
            import sqlite3
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = parsed.hostname or ""
            # Edge default path on Windows
            cookie_paths = [
                Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data" / "Default" / "Cookies",
                Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Cookies",
            ]
            for cp in cookie_paths:
                if not cp.exists():
                    continue
                tmp = cp.with_suffix(".tmp")
                try:
                    import shutil
                    shutil.copy2(cp, tmp)
                except Exception:
                    continue
                try:
                    con = sqlite3.connect(str(tmp))
                    cur = con.cursor()
                    cur.execute(
                        "SELECT host_key, name, value FROM cookies WHERE host_key LIKE ? OR host_key LIKE ?",
                        (f"%{host}%", f".{host}%"),
                    )
                    pairs = [f"{row[1]}={row[2]}" for row in cur.fetchall() if row[1] and row[2]]
                    con.close()
                    tmp.unlink(missing_ok=True)
                    if pairs:
                        return "; ".join(pairs[:20])
                except Exception:
                    try:
                        tmp.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass
        return None

    def search(self, query: str) -> str:
        # Try browser_exec first if available
        if self._has_browser_exec:
            url = f"https://duckduckgo.com/html/?q={query.replace(' ', '+')}"
            res = self._exec(f"goto_url('{url}')\nwait_for_load()\njs('document.body.innerText')")
            text = str(res.get("result", "")) if isinstance(res, dict) else str(res)
            if text and text.strip() and "captcha" not in text.lower() and "confirm" not in text.lower():
                return text[:5000]
        # Fallback chain: Google -> Bing -> Brave -> DuckDuckGo lite
        engines = [
            f"https://www.google.com/search?q={query.replace(' ', '+')}",
            f"https://www.bing.com/search?q={query.replace(' ', '+')}",
            f"https://search.brave.com/search?q={query.replace(' ', '+')}",
            f"https://lite.duckduckgo.com/lite/?q={query.replace(' ', '+')}",
        ]
        for url in engines:
            text = self._http_get(url)
            if text and not text.startswith("ERROR:") and len(text) > 100:
                return text[:5000]
        return "Search failed: all engines blocked or unavailable"

    def read_page(self, url: str) -> str:
        if self._has_browser_exec:
            res = self._exec(f"goto_url('{url}')\nwait_for_load()\njs('document.body.innerText')")
            text = str(res.get("result", "")) if isinstance(res, dict) else str(res)
            if text and text.strip():
                return text[:8000]
        return self._http_get(url)

    def show(self, url: str) -> None:
        """Open a visible browser tab for dad to see."""
        if not self._has_browser_exec:
            return
        try:
            from browser_exec import browser_exec
            browser_exec(code=f"new_tab('{url}')\nwait_for_load()", session=self._visible_session, local=True)
        except Exception:
            pass


class WindowTools:
    """Focus Windows app windows."""

    def focus(self, title_fragment: str) -> str:
        try:
            import subprocess
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$p = Get-Process | Where-Object { $_.MainWindowTitle -like '*" + title_fragment + "*' } | Select-Object -First 1; "
                "if ($p) { $wshell = New-Object -ComObject wscript.shell; $wshell.AppActivate($p.MainWindowTitle); 'ok' } else { 'not found' }"
            )
            subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True)
            return f"focus window containing '{title_fragment}'"
        except Exception as e:
            return f"ERROR: {e}"


__all__ = ["FileTools", "BrowserTools", "WindowTools"]
