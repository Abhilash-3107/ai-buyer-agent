"""The uvicorn entry point: `uvicorn app.main:app`. Reads the repo-root `.env` before building the app."""
from __future__ import annotations

from .api.app import create_app
from .config import load_env

load_env()
app = create_app()
