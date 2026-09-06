"""
Force-run the standalone Nova GUI from the local neuro_child package,
using the Hermes venv Python so torch/transformers/peft are available.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent

# Prefer Hermes venv if available so torch/transformers resolve.
VENV_CANDIDATES = [
    Path(os.environ.get("VIRTUAL_ENV", "")) / "Scripts" / "python.exe",
    PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
    Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent" / "venv" / "Scripts" / "python.exe",
]
for cand in VENV_CANDIDATES:
    if cand.exists():
        try:
            os.execv(str(cand), [str(cand), *sys.argv])
        except Exception:
            pass
        break

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

for mod in list(sys.modules.keys()):
    if mod.startswith("neuro_child"):
        del sys.modules[mod]

from neuro_child.gui import ChildGUI


def main() -> None:
    ChildGUI("Nova").run()


if __name__ == "__main__":
    main()
