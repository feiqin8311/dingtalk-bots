"""Make the monorepo root (for `shared`) and this app's dir importable when pytest runs from the app."""

import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP_DIR.parents[1]
for _path in (str(_REPO_ROOT), str(_APP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
