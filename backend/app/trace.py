"""The single record of a run (D33): ordered events, appended as JSONL and optionally pushed to a live callback.

The CLI, the Phase 6 stream and the Phase 5 eval all read these same events.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .serialize import strict_json


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    turn: int  # 0 = before the first model call
    type: str  # run_started | llm_request | llm_response | tool_call | tool_result | harness_step | nudge
    #            | recovered_tool_call | budget_locked | decision | verification | flagged | run_finished | error
    #            llm_request: the messages added since the previous request (+ the tool list on the first one).
    #            harness_step: a step the code ran for one agent tool call: its request check (stage "request":
    #            ACCEPTED, REJECTED or LOCKED), then for a write the validator, approval and supplier.
    data: dict  # JSON-safe
    ts: float  # seconds since run start


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
