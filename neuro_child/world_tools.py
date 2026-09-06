"""
World tools for Nova: file system, browser automation, window focus.
"""
from __future__ import annotations

import os
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
    Browser automation using the user's actual Chromium profile/cookies/cache.
    Default mode: headless/local backend so Nova can search/log in as you.
    Only opens visible browser when explicitly requested.
    """

    def __init__(self, local: bool = True, session: str = "nova_default") -> None:
        self._local = local
        self._session = session
        self._visible_session = "nova_visible"

    def _exec(self, code: str, *, local: Optional[bool] = None, session: Optional[str] = None) -> Dict[str, Any]:
        try:
            from browser_exec import browser_exec
            kw: Dict[str, Any] = {"code": code, "session": session or self._session}
            if local is None:
                kw["local"] = self._local
            else:
                kw["local"] = local
            return browser_exec(**kw)
        except Exception as e:
            return {"error": str(e)}

    def search(self, query: str) -> str:
        url = f"https://duckduckgo.com/html/?q={query.replace(' ', '+')}"
        res = self._exec(f"goto_url('{url}')\nwait_for_load()\njs('document.body.innerText')")
        text = str(res.get("result", "")) if isinstance(res, dict) else str(res)
        return text[:5000]

    def read_page(self, url: str) -> str:
        res = self._exec(f"goto_url('{url}')\nwait_for_load()\njs('document.body.innerText')")
        text = str(res.get("result", "")) if isinstance(res, dict) else str(res)
        return text[:8000]

    def show(self, url: str) -> None:
        """Open a visible browser tab for dad to see."""
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
