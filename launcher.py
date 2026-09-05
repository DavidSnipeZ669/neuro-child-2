"""
Force-run the standalone Nova GUI from the local neuro_child package,
bypassing any stale editable install path.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Canonical project root: parent of the directory containing this launcher.
APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent

# Ensure the local package is importable even if another install shadows it.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force reimport if stale copies are already cached.
for mod in list(sys.modules.keys()):
    if mod.startswith("neuro_child"):
        del sys.modules[mod]

from neuro_child.gui import ChildGUI


def main() -> None:
    ChildGUI("Nova").run()


if __name__ == "__main__":
    main()
