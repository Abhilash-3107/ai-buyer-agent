"""Settings: where data lives, resolved when first asked for (not at import), plus explicit `.env` loading.

Each path can be overridden by an env var (DATA_DIR, RUNS_DIR, EVAL_DIR, FRONTEND_DIST).
Tests swap the cached settings with `monkeypatch.setattr(config, "_settings", Settings(...))`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    runs_dir: Path
    eval_dir: Path
    frontend_dist: Path

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.environ.get("DATA_DIR") or _BACKEND / "data")
        return cls(data_dir=data_dir,
                   runs_dir=Path(os.environ.get("RUNS_DIR") or data_dir / "runs"),
                   eval_dir=Path(os.environ.get("EVAL_DIR") or _REPO / "docs" / "eval"),
                   frontend_dist=Path(os.environ.get("FRONTEND_DIST") or _REPO / "frontend" / "dist"))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def load_env() -> None:
    """Load the repo-root `.env` into os.environ without overriding variables already set. Safe to call twice."""
    load_dotenv(_REPO / ".env", override=False)
