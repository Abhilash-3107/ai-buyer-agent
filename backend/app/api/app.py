"""The application factory: routes, CORS and (when a built UI exists) the static frontend."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from ..config import get_settings
from .routes import router


def serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built UI: real files as they are, any other non-API path gets index.html (client-side routes)."""
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        target = (dist / path).resolve()
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "not found")
        return FileResponse(target if target.is_file() and dist.resolve() in target.parents else dist / "index.html")


def create_app() -> FastAPI:
    """Build the app from the current settings (the same ones the routes read)."""
    settings = get_settings()
    app = FastAPI(title="AI Buyer Agent")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    if settings.frontend_dist.is_dir():
        serve_frontend(app, settings.frontend_dist)
    return app
