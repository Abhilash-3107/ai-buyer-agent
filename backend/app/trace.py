"""The single record of a run (D33): ordered events, appended as JSONL and optionally pushed to a live callback.

The CLI, the Phase 6 stream and the Phase 5 eval all read these same events.
"""
from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    turn: int  # 0 = before the first model call
    type: str  # run_started | llm_request | llm_response | tool_call | tool_result | harness_step | nudge
    #            | recovered_tool_call | budget_locked | decision | verification | flagged | run_finished | error
    #            llm_request: the messages added since the previous request (+ the tool list on the first one).
    #            harness_step: a validator, approval or supplier step the code ran for one write tool call.
    data: dict  # JSON-safe
    ts: float  # seconds since run start


def _strict(value):
    """JSON-safe for browsers: JSON.parse rejects Infinity and NaN, so they become strings."""
    if isinstance(value, float) and not math.isfinite(value):
        return "nan" if math.isnan(value) else "infinite" if value > 0 else "-infinite"
    if isinstance(value, dict):
        return {k: _strict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strict(v) for v in value]
    return value


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
        event = TraceEvent(self._seq, turn, type, _strict(data), round(time.perf_counter() - self._start, 3))
        if self.path is not None:
            with self.path.open("a") as f:
                f.write(json.dumps(asdict(event), default=str, allow_nan=False) + "\n")
        if self.on_event is not None:
            self.on_event(event)
        return event
