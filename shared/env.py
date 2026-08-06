from __future__ import annotations

import os
from pathlib import Path


def load_env_files(paths: list[Path]) -> None:
    """Load KEY=VALUE files. First file wins for each key (does not override existing os.environ)."""
    for env_path in paths:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def monorepo_env_paths(root: Path, *extra_app_envs: Path) -> list[Path]:
    """Prefer single repo-root .env; optional app .env only fills missing keys."""
    paths = [root / ".env"]
    paths.extend(extra_app_envs)
    paths.append(Path.cwd() / ".env")
    return paths
