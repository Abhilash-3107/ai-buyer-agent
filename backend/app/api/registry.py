"""The run registry: live runs in this process, their background threads, and the `.api.json` sidecars on disk."""
from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import HTTPException

from ..agent.llm import LLMClient
from ..agent.service import run_agent
from ..config import get_settings
from ..evaluation.baselines import BaselineClient
from ..evaluation.scoring import score_run
from ..purchasing.types import Run
from ..scenarios.catalog import SCENARIOS

RUN_ID = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{6}$")  # also keeps user input out of the glob below


# --- the model behind the runs ---------------------------------------------------------------------
def _model_name(client: LLMClient | BaselineClient) -> str:
    return f"baseline:{client.name}" if isinstance(client, BaselineClient) else client.config.model


# --- the registry ----------------------------------------------------------------------------------
class Live:
    """One run as the API sees it: its identity, the events so far, and a condition SSE readers wait on."""

    def __init__(self, run: Run, model: str, events: list[dict] | None = None, done: bool = False,
                 scorecard: dict | None = None):
        self.run, self.model, self.scorecard = run, model, scorecard
        self.events: list[dict] = events or []
        self.done = done
        self.cond = threading.Condition()

    def push(self, event: dict) -> None:
        with self.cond:
            self.events.append(event)
            self.cond.notify_all()

    def finish(self) -> None:
        with self.cond:
            self.done = True
            self.cond.notify_all()

    def last(self, type: str) -> dict | None:
        return next((e["data"] for e in reversed(list(self.events)) if e["type"] == type), None)


REGISTRY: dict[str, Live] = {}
REGISTRY_LOCK = threading.RLock()


def _sidecar(run: Run) -> Path:
    return run.path.with_suffix(".api.json")


def _save_sidecar(live: Live) -> None:
    _sidecar(live.run).write_text(json.dumps({"model": live.model, "scorecard": live.scorecard},
                                             default=str, allow_nan=False))


def load_from_disk(run_id: str) -> Live | None:
    """A finished run of an earlier server process, rebuilt from its trace file and sidecar."""
    found = next(iter(get_settings().runs_dir.glob(f"*__{run_id}.api.json")), None) if RUN_ID.match(run_id) else None
    if found is None:
        return None
    side = json.loads(found.read_text())
    trace = found.with_name(found.name.removesuffix(".api.json") + ".trace.jsonl")
    events = [json.loads(line) for line in trace.read_text().splitlines() if line] if trace.exists() else []
    if not events:
        return None
    d = events[0]["data"]
    run = Run(run_id, d["scenario_id"], d["node_id"], d["sku"], found.with_name(found.name.removesuffix(".api.json") + ".db"))
    return Live(run, side["model"], events, True, side["scorecard"])


def get_live(run_id: str) -> Live:
    with REGISTRY_LOCK:
        live = REGISTRY.get(run_id) or load_from_disk(run_id)
        if live is None:
            raise HTTPException(404, f"unknown run {run_id}")
        return REGISTRY.setdefault(run_id, live)


def start_run(scenario_id: str, client: LLMClient | BaselineClient) -> Live:
    """Run the agent in a thread and return once the run exists (its first event carries the run id)."""
    ready, box = threading.Event(), {}
    model = _model_name(client)

    def on_event(e) -> None:
        if e.type == "run_started":
            d = e.data
            run = Run(d["run_id"], scenario_id, d["node_id"], d["sku"], get_settings().runs_dir / f"{scenario_id}__{d['run_id']}.db")
            box["live"] = Live(run, model)
            with REGISTRY_LOCK:
                REGISTRY[run.run_id] = box["live"]
            _save_sidecar(box["live"])
            ready.set()
        box["live"].push(asdict(e))

    def work() -> None:
        live = None
        try:
            result = run_agent(scenario_id, client, on_event=on_event)
            live = box["live"]
            try:
                live.scorecard = asdict(score_run(SCENARIOS[scenario_id], result, model))
                _save_sidecar(live)
            finally:
                result.conn.close()
        except Exception as exc:  # noqa: BLE001 - a bug in a run must end its stream, not hang the viewer
            box["error"] = exc
            live = box.get("live")
            if live:
                event = {"seq": len(live.events) + 1, "turn": 0, "type": "error", "ts": 0,
                         "data": {"message": f"{type(exc).__name__}: {exc}"}}
                with live.run.path.with_suffix(".trace.jsonl").open("a") as f:  # a restart shows the message too
                    f.write(json.dumps(event, default=str, allow_nan=False) + "\n")
                live.push(event)
        finally:
            ready.set()
            if live:
                live.finish()

    threading.Thread(target=work, daemon=True, name=f"run-{scenario_id}").start()
    ready.wait()
    if "live" not in box:
        raise HTTPException(500, f"the run could not start: {box.get('error')}")
    return box["live"]
