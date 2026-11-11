"""Phase 6 HTTP API (D41-D44): a window onto the same agent, trace, database and scorer the CLI and eval use.

Runs execute in a background thread and publish their trace events to an in-process registry, which the
SSE endpoint replays and then follows. Each API run leaves a `.api.json` sidecar (model, scorecard) next to its
database and trace, so a restarted server can still read its history. No business logic lives here.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import actions, evaluate, runs
from .agent import run_agent
from .baselines import BaselineClient, make_client
from .db import connect
from .llm import LLMClient, LLMConfig
from .runs import Run
from .scenarios import SCENARIOS
from .scoring import score_run

EVAL_DIR = evaluate.DEFAULT_OUT  # tests point this at a temp directory
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
RUN_ID = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{6}$")  # also keeps user input out of the glob below
LIST_LIMIT = 50


# --- the model behind the runs (make_client comes from baselines; tests patch api.make_client) ------
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
_REGISTRY_LOCK = threading.RLock()


def _sidecar(run: Run) -> Path:
    return run.path.with_suffix(".api.json")


def _save_sidecar(live: Live) -> None:
    _sidecar(live.run).write_text(json.dumps({"model": live.model, "scorecard": live.scorecard},
                                             default=str, allow_nan=False))


def _from_disk(run_id: str) -> Live | None:
    """A finished run of an earlier server process, rebuilt from its trace file and sidecar."""
    found = next(iter(runs.RUNS_DIR.glob(f"*__{run_id}.api.json")), None) if RUN_ID.match(run_id) else None
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


def _get(run_id: str) -> Live:
    with _REGISTRY_LOCK:
        live = REGISTRY.get(run_id) or _from_disk(run_id)
        if live is None:
            raise HTTPException(404, f"unknown run {run_id}")
        return REGISTRY.setdefault(run_id, live)


def _start(scenario_id: str, client: LLMClient | BaselineClient) -> Live:
    """Run the agent in a thread and return once the run exists (its first event carries the run id)."""
    ready, box = threading.Event(), {}
    model = _model_name(client)

    def on_event(e) -> None:
        if e.type == "run_started":
            d = e.data
            run = Run(d["run_id"], scenario_id, d["node_id"], d["sku"], runs.RUNS_DIR / f"{scenario_id}__{d['run_id']}.db")
            box["live"] = Live(run, model)
            with _REGISTRY_LOCK:
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


# --- building the answers --------------------------------------------------------------------------
def _outcome(live: Live) -> str | None:
    fin = live.last("run_finished")
    return fin["outcome"] if fin else "INTERRUPTED" if live.done else None


def _verification(live: Live) -> dict | None:
    v = live.last("verification")
    return v and {"passed": v["passed"], "findings": [{"code": f["code"], "message": f["message"]} for f in v["findings"]]}


def _decision(live: Live) -> dict | None:
    if _outcome(live) not in (None, "DECIDED"):
        return None  # the loop discards a decision the verifier rejected when the run did not end DECIDED
    d = live.last("decision")
    return d and {k: d[k] for k in ("decision", "new_units", "daily_demand_used", "key_factors", "actions_taken",
                                    "confidence", "summary")}


def _totals(live: Live) -> dict:
    fin = live.last("run_finished")
    if fin:
        return {"turns": fin["steps"], "tokens_in": fin["tokens_in"], "tokens_out": fin["tokens_out"],
                "latency_s": fin["latency_s"]}
    llm = [e["data"] for e in list(live.events) if e["type"] == "llm_response"]
    return {"turns": len(llm), "tokens_in": sum(d["usage"].get("input_tokens", 0) for d in llm),
            "tokens_out": sum(d["usage"].get("output_tokens", 0) for d in llm),
            "latency_s": list(live.events)[-1]["ts"] if live.events else 0}


def _scorecard(live: Live) -> dict | None:
    c = live.scorecard
    return c and {"passed": c["passed"], "checks": c["checks"], "new_buy_units": c["new_buy_units"],
                  "info_read_by_agent": c["info_read_by_agent"]}


def _rows(live: Live, sql: str, *params) -> list[dict]:
    """Read from the run's database; empty if the agent thread holds it locked at this instant."""
    conn = connect(live.run.path)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _summary(live: Live) -> dict:
    run = live.run
    return {
        "run_id": run.run_id, "scenario_id": run.scenario_id, "status": "finished" if live.done else "running",
        "model": live.model, "outcome": _outcome(live), "decision": _decision(live),
        "verification": _verification(live), "scorecard": _scorecard(live),
        "purchase_orders": _rows(
            live, "SELECT po.po_id, po.supplier_id, s.name AS supplier_name, po.status, po.qty_ordered, "
                  "po.qty_confirmed, po.unit_cost, ROUND(po.qty_ordered * po.unit_cost, 2) AS value, "
                  "po.expected_arrival, po.created_by, po.parent_po_id FROM purchase_orders po "
                  "JOIN suppliers s ON s.supplier_id = po.supplier_id WHERE po.sku = ? ORDER BY po.po_id", run.sku),
        "escalations": _rows(live, "SELECT escalation_id, kind, po_id, summary, status, created_at "
                                   "FROM escalations ORDER BY rowid"),
        "totals": _totals(live)}


def _listing(live: Live) -> dict:
    d, card = _decision(live), live.scorecard
    started = datetime.strptime(live.run.run_id[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    return {"run_id": live.run.run_id, "scenario_id": live.run.scenario_id,
            "status": "finished" if live.done else "running", "outcome": _outcome(live),
            "decision": d["decision"] if d else None, "passed": card["passed"] if card else None,
            "started_at": started.isoformat()}


def _stream(live: Live):
    """Replay every event from seq 1, then follow new ones, then say the stream has ended."""
    sent = 0
    while True:
        with live.cond:
            live.cond.wait_for(lambda n=sent: len(live.events) > n or live.done, timeout=15)
            batch, done = live.events[sent:], live.done
        sent += len(batch)
        for event in batch:
            yield f"data: {json.dumps(event, default=str, allow_nan=False)}\n\n"
        if done and not batch:
            yield "event: end\ndata: {}\n\n"
            return
        if not batch:
            yield ": keepalive\n\n"  # lets a disconnected client's reader thread notice and stop


# --- routes ----------------------------------------------------------------------------------------
app = FastAPI(title="AI Buyer Agent")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


class RunRequest(BaseModel):
    scenario_id: str


class Note(BaseModel):
    note: str = ""


@app.get("/api/health")
def health() -> dict:
    config = LLMConfig.from_env()
    demo = config.model.startswith("baseline:")
    return {"ok": True, "model": config.model, "local": demo or config.is_local, "demo": demo}


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    return [{"id": s.id, "group": s.group, "title": s.title, "situation": s.situation,
             "trigger_type": s.trigger["type"],
             "expected": {"decision": s.expected.decision, "new_buy_qty": list(s.expected.new_buy_qty),
                          "allowed_suppliers": list(s.expected.allowed_suppliers) if s.expected.allowed_suppliers else None,
                          "escalation": s.expected.escalation, "worked_example": s.expected.worked_example}}
            for s in SCENARIOS.values()]


@app.post("/api/runs", status_code=201)
def create_run(body: RunRequest) -> dict:
    if body.scenario_id not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario {body.scenario_id}")
    try:
        client = make_client()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
    live = _start(body.scenario_id, client)
    return {"run_id": live.run.run_id, "scenario_id": body.scenario_id}


@app.get("/api/runs")
def list_runs() -> list[dict]:
    for side in sorted(runs.RUNS_DIR.glob("*.api.json"), key=lambda p: p.name.split("__")[-1], reverse=True)[:LIST_LIMIT]:
        run_id = side.name.split("__")[-1].removesuffix(".api.json")
        with _REGISTRY_LOCK:
            if run_id not in REGISTRY and (live := _from_disk(run_id)):
                REGISTRY[run_id] = live
    with _REGISTRY_LOCK:
        lives = list(REGISTRY.values())
    return [_listing(live) for live in sorted(lives, key=lambda lv: lv.run.run_id, reverse=True)][:LIST_LIMIT]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _summary(_get(run_id))


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str) -> StreamingResponse:
    return StreamingResponse(_stream(_get(run_id)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _decide(run_id: str, escalation_id: str, body: Note | None, act) -> dict:
    note = (body or Note()).note
    live = _get(run_id)
    if not live.done:
        raise HTTPException(409, "the run is still working; wait for it to finish")
    conn = connect(live.run.path)
    try:
        if conn.execute("SELECT 1 FROM escalations WHERE escalation_id = ?", (escalation_id,)).fetchone() is None:
            raise HTTPException(404, f"unknown escalation {escalation_id}")
        result = act(conn, live.run, escalation_id, note)
    finally:
        conn.close()
    if result.status == "NOT_ALLOWED":
        raise HTTPException(409, result.message)
    return {"ok": result.ok, "status": result.status, "message": result.message, "po_id": result.po_id,
            "supplier": asdict(result.supplier) if result.supplier else None}


@app.post("/api/runs/{run_id}/escalations/{escalation_id}/approve")
def approve(run_id: str, escalation_id: str, body: Note | None = None) -> dict:
    return _decide(run_id, escalation_id, body, actions.approve_po)


@app.post("/api/runs/{run_id}/escalations/{escalation_id}/reject")
def reject(run_id: str, escalation_id: str, body: Note | None = None) -> dict:
    return _decide(run_id, escalation_id, body, actions.reject_po)


@app.get("/api/eval")
def eval_reports() -> list[dict]:
    """The committed eval results, summarized by the same code that wrote their Markdown."""
    out = []
    for f in sorted(EVAL_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            s = evaluate.summarize(data["cards"])
            out.append({"name": data["name"], "kind": data["kind"], "repeats": data["repeats"],
                        "temperature": data["temperature"], "cards": data["cards"],
                        "summary": {"scenarios_passed": s["scenarios_passed"], "scenarios": s["scenarios"],
                                    "runs_passed": s["runs_passed"], "runs": s["runs"],
                                    "per_check": {k: list(v) for k, v in s["check_rates"].items()}}})
        except (ValueError, KeyError, TypeError, OSError):
            continue  # not an eval result (or one still being written): skip it
    return out


def serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built UI: real files as they are, any other non-API path gets index.html (client-side routes)."""
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        target = (dist / path).resolve()
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "not found")
        return FileResponse(target if target.is_file() and dist.resolve() in target.parents else dist / "index.html")


if FRONTEND_DIST.is_dir():
    serve_frontend(app, FRONTEND_DIST)
