"""The single record of a run (D33): ordered events, appended as JSONL and optionally pushed to a live callback.

The CLI, the Phase 6 stream and the Phase 5 eval all read these same events.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from ..serialize import strict_json
from .types import TraceEvent


class Trace:
    def __init__(self, path: Path | None, on_event: Callable[[TraceEvent], None] | None = None):
        self.path = path
        self.on_event = on_event
        self._seq = 0
        self._start = time.perf_counter()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")

    def emit(self, type: str, turn: int, **data) -> TraceEvent:
        self._seq += 1
        event = TraceEvent(self._seq, turn, type, strict_json(data), round(time.perf_counter() - self._start, 3))
        if self.path is not None:
            with self.path.open("a") as f:
                f.write(json.dumps(asdict(event), default=str, allow_nan=False) + "\n")
        if self.on_event is not None:
            self.on_event(event)
        return event
