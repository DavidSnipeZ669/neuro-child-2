"""
Neuro-sama/Neuro-child desktop interaction.

This uses the Hermes `computer_use` tool under the hood to:
- Capture the screen
- Click elements by index or coordinates
- Type and press keys
- List apps/windows
- Scroll and drag
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _computer_use(**kwargs: Any) -> Dict[str, Any]:
    try:
        from hermes_tools import computer_use as _computer_use_tool
        return _computer_use_tool(**kwargs)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"computer_use unavailable: {exc}",
            "args": kwargs,
        }


class Desktop:
    def __init__(self, capture_mode: str = "som"):
        self.capture_mode = capture_mode
        self.last_capture: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Capture / perception
    # ------------------------------------------------------------------
    def capture(self, app: Optional[str] = None) -> Dict[str, Any]:
        result = _computer_use(
            action="capture",
            mode=self.capture_mode,
            app=app or "screen",
        )
        self.last_capture = result
        return result

    # ------------------------------------------------------------------
    # High-level observation: turn a capture into a text summary
    # ------------------------------------------------------------------
    def summarize(self, capture: Optional[Dict[str, Any]] = None) -> str:
        capture = capture or self.last_capture or self.capture()
        if not capture.get("ok", True):
            return f"Desktop capture unavailable: {capture.get('error')}"

        parts: List[str] = []

        if "title" in capture:
            parts.append(f"Window: {capture['title']}")
        if "app" in capture:
            parts.append(f"App: {capture['app']}")

        ax = capture.get("ax_tree") or capture.get("accessibility") or []
        if not ax:
            ax = capture.get("nodes") or []

        visible_texts: List[str] = []
        for node in ax:
            name = node.get("name") or node.get("title") or node.get("value") or ""
            role = node.get("role") or node.get("type") or ""
            if name:
                visible_texts.append(f"{role}: {name}")

        if visible_texts:
            parts.append("Visible UI elements: " + "; ".join(visible_texts[:20]))

        screenshot = capture.get("screenshot_path") or capture.get("screenshot")
        if screenshot:
            parts.append(f"Screenshot: {screenshot}")

        return "\n".join(parts) if parts else "Screen captured, no readable text found."

    def observe(self, app: Optional[str] = None) -> Dict[str, Any]:
        return self.capture(app)

    # ------------------------------------------------------------------
    # Input actions
    # ------------------------------------------------------------------
    def click(
        self,
        element: Optional[int] = None,
        coordinate: Optional[list[int]] = None,
        button: str = "left",
        capture_after: bool = True,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "action": "click",
            "button": button,
            "capture_after": capture_after,
        }
        if element is not None:
            kwargs["element"] = element
        elif coordinate is not None:
            kwargs["coordinate"] = coordinate
        else:
            raise ValueError("Provide either element index or coordinate")
        return _computer_use(**kwargs)

    def double_click(
        self,
        element: Optional[int] = None,
        coordinate: Optional[list[int]] = None,
        capture_after: bool = True,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "action": "double_click",
            "capture_after": capture_after,
        }
        if element is not None:
            kwargs["element"] = element
        elif coordinate is not None:
            kwargs["coordinate"] = coordinate
        else:
            raise ValueError("Provide either element index or coordinate")
        return _computer_use(**kwargs)

    def type_text(self, text: str, capture_after: bool = False) -> Dict[str, Any]:
        return _computer_use(
            action="type",
            text=text,
            capture_after=capture_after,
        )

    def press_keys(self, keys: str, capture_after: bool = False) -> Dict[str, Any]:
        return _computer_use(
            action="key",
            keys=keys,
            capture_after=capture_after,
        )

    def scroll(
        self,
        direction: str = "down",
        amount: int = 3,
        element: Optional[int] = None,
        coordinate: Optional[list[int]] = None,
        capture_after: bool = False,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "action": "scroll",
            "direction": direction,
            "amount": amount,
            "capture_after": capture_after,
        }
        if element is not None:
            kwargs["element"] = element
        elif coordinate is not None:
            kwargs["coordinate"] = coordinate
        return _computer_use(**kwargs)

    def drag(
        self,
        from_element: Optional[int] = None,
        to_element: Optional[int] = None,
        from_coordinate: Optional[list[int]] = None,
        to_coordinate: Optional[list[int]] = None,
        capture_after: bool = True,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "action": "drag",
            "capture_after": capture_after,
        }
        if from_element is not None:
            kwargs["from_element"] = from_element
        elif from_coordinate is not None:
            kwargs["from_coordinate"] = from_coordinate
        else:
            raise ValueError("Provide from_element or from_coordinate")

        if to_element is not None:
            kwargs["to_element"] = to_element
        elif to_coordinate is not None:
            kwargs["to_coordinate"] = to_coordinate
        else:
            raise ValueError("Provide to_element or to_coordinate")

        return _computer_use(**kwargs)

    def wait(self, seconds: float = 1.0) -> Dict[str, Any]:
        return _computer_use(action="wait", seconds=seconds)

    # ------------------------------------------------------------------
    # App / window management
    # ------------------------------------------------------------------
    def list_apps(self) -> Dict[str, Any]:
        return _computer_use(action="list_apps")

    def focus_app(self, app: str, raise_window: bool = False) -> Dict[str, Any]:
        return _computer_use(action="focus_app", app=app, raise_window=raise_window)
