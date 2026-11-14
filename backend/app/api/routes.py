"""Every /api endpoint, plus the read model they serve (a run's summary, listing and event stream)."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..agent.llm import LLMConfig, make_client
from ..agent.types import RunOutcome
from ..config import get_settings
from ..db import connect
from ..evaluation.service import summarize
from ..purchasing import actions
from ..purchasing.types import ActionStatus
from ..scenarios.catalog import SCENARIOS
from . import registry
from .registry import Live
from .types import Note, RunRequest

LIST_LIMIT = 50
router = APIRouter()


# --- building the answers --------------------------------------------------------------------------
def _outcome(live: Live) -> str | None:
    fin = live.last("run_finished")
    return fin["outcome"] if fin else RunOutcome.INTERRUPTED if live.done else None


def _verification(live: Live) -> dict | None:
    v = live.last("verification")
    return v and {"passed": v["passed"], "findings": [{"code": f["code"], "message": f["message"]} for f in v["findings"]]}


def _decision(live: Live) -> dict | None:
    if _outcome(live) not in (None, RunOutcome.DECIDED):
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
                  # runs saved before phase 9 have info_read_by_agent and no repeat count
                  "info_read": c.get("info_read", c.get("info_read_by_agent", [])), "repeat_reads": c.get("repeat_reads")}


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
@router.get("/api/health")
def health() -> dict:
    config = LLMConfig.from_env()
    demo = config.model.startswith("baseline:")
    return {"ok": True, "model": config.model, "local": demo or config.is_local, "demo": demo}


@router.get("/api/scenarios")
def scenarios() -> list[dict]:
    return [{"id": s.id, "group": s.group, "title": s.title, "situation": s.situation,
             "summary": s.summary,
             "trigger_type": s.trigger["type"],
             "expected": {"decision": s.expected.decision, "new_buy_qty": list(s.expected.new_buy_qty),
                          "allowed_suppliers": list(s.expected.allowed_suppliers) if s.expected.allowed_suppliers else None,
                          "escalation": s.expected.escalation, "worked_example": s.expected.worked_example}}
            for s in SCENARIOS.values()]


@router.post("/api/runs", status_code=201)
def create_run(body: RunRequest) -> dict:
    if body.scenario_id not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario {body.scenario_id}")
    try:
        client = make_client()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
    live = registry.start_run(body.scenario_id, client)
    return {"run_id": live.run.run_id, "scenario_id": body.scenario_id}


@router.get("/api/runs")
def list_runs() -> list[dict]:
    for side in sorted(get_settings().runs_dir.glob("*.api.json"), key=lambda p: p.name.split("__")[-1], reverse=True)[:LIST_LIMIT]:
        run_id = side.name.split("__")[-1].removesuffix(".api.json")
        with registry.REGISTRY_LOCK:
            if run_id not in registry.REGISTRY and (live := registry.load_from_disk(run_id)):
                registry.REGISTRY[run_id] = live
    with registry.REGISTRY_LOCK:
        lives = list(registry.REGISTRY.values())
    return [_listing(live) for live in sorted(lives, key=lambda lv: lv.run.run_id, reverse=True)][:LIST_LIMIT]


@router.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _summary(registry.get_live(run_id))


@router.get("/api/runs/{run_id}/events")
def run_events(run_id: str) -> StreamingResponse:
    return StreamingResponse(_stream(registry.get_live(run_id)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _decide(run_id: str, escalation_id: str, body: Note | None, act) -> dict:
    note = (body or Note()).note
    live = registry.get_live(run_id)
    if not live.done:
        raise HTTPException(409, "the run is still working; wait for it to finish")
    conn = connect(live.run.path)
    try:
        if conn.execute("SELECT 1 FROM escalations WHERE escalation_id = ?", (escalation_id,)).fetchone() is None:
            raise HTTPException(404, f"unknown escalation {escalation_id}")
        result = act(conn, live.run, escalation_id, note)
    finally:
        conn.close()
    if result.status == ActionStatus.NOT_ALLOWED:
        raise HTTPException(409, result.message)
    return {"ok": result.ok, "status": result.status, "message": result.message, "po_id": result.po_id,
            "supplier": asdict(result.supplier) if result.supplier else None}


@router.post("/api/runs/{run_id}/escalations/{escalation_id}/approve")
def approve(run_id: str, escalation_id: str, body: Note | None = None) -> dict:
    return _decide(run_id, escalation_id, body, actions.approve_po)


@router.post("/api/runs/{run_id}/escalations/{escalation_id}/reject")
def reject(run_id: str, escalation_id: str, body: Note | None = None) -> dict:
    return _decide(run_id, escalation_id, body, actions.reject_po)


@router.get("/api/eval")
def eval_reports() -> list[dict]:
    """The committed eval results, summarized by the same code that wrote their Markdown."""
    out = []
    for f in sorted(get_settings().eval_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            s = summarize(data["cards"])
            out.append({"name": data["name"], "kind": data["kind"], "repeats": data["repeats"],
                        "temperature": data["temperature"], "cards": data["cards"],
                        "summary": {"scenarios_passed": s["scenarios_passed"], "scenarios": s["scenarios"],
                                    "runs_passed": s["runs_passed"], "runs": s["runs"],
                                    "per_check": {k: list(v) for k, v in s["check_rates"].items()}}})
        except (ValueError, KeyError, TypeError, OSError):
            continue  # not an eval result (or one still being written): skip it
    return out
