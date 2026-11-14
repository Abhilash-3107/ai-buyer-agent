"""Request bodies."""
from __future__ import annotations

from pydantic import BaseModel


class RunRequest(BaseModel):
    scenario_id: str


class Note(BaseModel):
    note: str = ""
