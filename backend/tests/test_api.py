"""The HTTP API: contract shapes, the live event stream, human approval, restarts, demo mode and the eval page."""
import json
import shutil
import sqlite3
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scripted import call, investigate, reply, scripted_llm, submit

from app.api import registry, routes
from app.api.app import create_app, serve_frontend
from app.config import Settings, get_settings
from app.purchasing import supplier
from app.scenarios.catalog import SCENARIOS

REAL_EVAL_DIR = Settings.from_env().eval_dir  # the committed reports
S1 = {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "daily_demand": 40, "reason": "r"}
S4 = {"sku": "SKU-4001", "supplier_id": "SUP-METRO", "daily_demand": 60, "reason": "r", "justification": "j"}


@pytest.fixture
def client(use_settings, monkeypatch):
    use_settings()
    monkeypatch.setattr(registry, "REGISTRY", {})
    monkeypatch.delenv("LLM_MODEL", raising=False)
    return TestClient(create_app())


def use_script(monkeypatch, *script):
    monkeypatch.setattr(routes, "make_client", lambda: scripted_llm(list(script)))


S1_SCRIPT = [investigate("SKU-1002"),
             reply(call("create_po", {**S1, "qty": 800})), reply(call("create_po", {**S1, "qty": 192})),
             reply(submit("MODIFY", 192))]
S4_SCRIPT = [reply(call("create_po", {**S4, "qty": 396})),
             reply(call("escalate_to_human", {"kind": "BUDGET_INCREASE", "summary": "need $1,080 more"})),
             reply(submit("MODIFY", 396, demand=60.0))]


def start(client, scenario_id="S1-MODIFY"):
    r = client.post("/api/runs", json={"scenario_id": scenario_id})
    assert r.status_code == 201 and r.json()["scenario_id"] == scenario_id
    return r.json()["run_id"]


def read_events(client, run_id):
    """(events, saw_end): the SSE stream parsed; the call returns only once the server sent `event: end`."""
    with client.stream("GET", f"/api/runs/{run_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    events = [json.loads(b[len("data: "):]) for b in text.split("\n\n") if b.startswith("data: ")]
    return events, text.rstrip().endswith("event: end\ndata: {}")


def pending_escalation(summary):
    return next(e for e in summary["escalations"] if e["kind"] == "APPROVAL")


def po(summary, po_id):
    return next(p for p in summary["purchase_orders"] if p["po_id"] == po_id)


def test_health_and_scenarios(client):
    health = client.get("/api/health").json()
    assert set(health) == {"ok", "model", "local", "demo"} and health["ok"] and not health["demo"]

    listed = client.get("/api/scenarios").json()
    assert [s["id"] for s in listed] == list(SCENARIOS)
    s4 = next(s for s in listed if s["id"] == "S4-BUDGET")
    assert set(s4) == {"id", "group", "title", "situation", "summary", "trigger_type", "expected"}
    assert s4["trigger_type"] == "RECOMMENDATION_REVIEW" and s4["group"] == 4
    assert s4["expected"] == {"decision": "MODIFY", "new_buy_qty": [120, 396], "allowed_suppliers": ["SUP-METRO"],
                              "escalation": "BUDGET_INCREASE", "worked_example": SCENARIOS["S4-BUDGET"].expected.worked_example}


def test_run_streams_events_and_summarizes(client, monkeypatch):
    use_script(monkeypatch, *S1_SCRIPT)
    run_id = start(client)

    events, ended = read_events(client, run_id)
    assert ended and [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[0]["type"] == "run_started" and events[-1]["type"] == "run_finished"
    assert set(events[0]) == {"seq", "turn", "type", "data", "ts"}
    replay, _ = read_events(client, run_id)  # a late subscriber gets the whole history again
    assert replay == events

    s = client.get(f"/api/runs/{run_id}").json()
    assert (s["status"], s["scenario_id"], s["model"], s["outcome"]) == ("finished", "S1-MODIFY", "scripted", "DECIDED")
    assert s["decision"]["decision"] == "MODIFY" and s["decision"]["new_units"] == 192
    assert s["verification"] == {"passed": True, "findings": []}
    assert s["scorecard"]["passed"] and s["scorecard"]["new_buy_units"] == 192
    assert [c["name"] for c in s["scorecard"]["checks"]] == ["decision", "information", "constraints", "action",
                                                              "validation", "recovery"]
    assert set(s["scorecard"]["checks"][0]) == {"name", "applicable", "passed", "reason"}
    mine = po(s, "PO-A001")
    assert (mine["status"], mine["qty_confirmed"], mine["created_by"], mine["supplier_name"]) == \
           ("CONFIRMED", 192, "agent", "Metro Wholesale")
    assert any(p["created_by"] != "agent" for p in s["purchase_orders"])  # the seeded POs are shown too
    assert s["totals"]["turns"] == 4 and s["totals"]["tokens_in"] == 400

    [row] = client.get("/api/runs").json()
    assert row["run_id"] == run_id and (row["status"], row["decision"], row["passed"]) == ("finished", "MODIFY", True)


def test_approve_submits_the_held_po_to_the_supplier(client, monkeypatch):
    use_script(monkeypatch, *S4_SCRIPT)
    run_id = start(client, "S4-BUDGET")
    read_events(client, run_id)
    s = client.get(f"/api/runs/{run_id}").json()
    esc = pending_escalation(s)
    assert (esc["status"], po(s, esc["po_id"])["status"]) == ("OPEN", "PENDING_APPROVAL")

    # the person deciding sees why it is held, not just a one-line summary
    assert set(esc) == {"escalation_id", "kind", "po_id", "summary", "details", "status", "created_at", "answer_note"}
    assert esc["details"]["po_value"] == 2376 and esc["details"]["reason"] and esc["answer_note"] is None

    r = client.post(f"/api/runs/{run_id}/escalations/{esc['escalation_id']}/approve", json={"note": "ok"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["po_id"] == esc["po_id"] and body["supplier"]["confirmed"] == 396

    s = client.get(f"/api/runs/{run_id}").json()
    assert po(s, esc["po_id"])["status"] == "CONFIRMED" and po(s, esc["po_id"])["qty_confirmed"] == 396
    assert pending_escalation(s)["status"] == "APPROVED" and pending_escalation(s)["answer_note"] == "ok"

    again = client.post(f"/api/runs/{run_id}/escalations/{esc['escalation_id']}/approve", json={"note": "x"})
    assert again.status_code == 409 and "detail" in again.json()
    assert client.post(f"/api/runs/{run_id}/escalations/{esc['escalation_id']}/reject", json={}).status_code == 409


def test_reject_cancels_the_held_po(client, monkeypatch):
    use_script(monkeypatch, *S4_SCRIPT)
    run_id = start(client, "S4-BUDGET")
    read_events(client, run_id)
    esc = pending_escalation(client.get(f"/api/runs/{run_id}").json())

    r = client.post(f"/api/runs/{run_id}/escalations/{esc['escalation_id']}/reject", json={"note": "too much"})
    assert r.status_code == 200 and r.json()["supplier"] is None
    s = client.get(f"/api/runs/{run_id}").json()
    assert po(s, esc["po_id"])["status"] == "CANCELLED" and pending_escalation(s)["status"] == "REJECTED"


@pytest.mark.parametrize("verb, status", [("accept", "ACCEPTED"), ("decline", "DECLINED")])
def test_a_human_answers_a_budget_escalation_without_touching_pos_or_the_score(client, monkeypatch, verb, status):
    use_script(monkeypatch, *S4_SCRIPT)
    run_id = start(client, "S4-BUDGET")
    read_events(client, run_id)
    before = client.get(f"/api/runs/{run_id}").json()
    budget = next(e for e in before["escalations"] if e["kind"] == "BUDGET_INCREASE")
    held = pending_escalation(before)

    r = client.post(f"/api/runs/{run_id}/escalations/{budget['escalation_id']}/{verb}", json={"note": "fine"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["supplier"] is None

    after = client.get(f"/api/runs/{run_id}").json()
    assert next(e for e in after["escalations"] if e["escalation_id"] == budget["escalation_id"])["status"] == status
    assert after["purchase_orders"] == before["purchase_orders"] and after["scorecard"] == before["scorecard"]
    with sqlite3.connect(next(get_settings().runs_dir.glob(f"*__{run_id}.db"))) as conn:
        (details,) = conn.execute("SELECT details_json FROM audit_log WHERE action = ?", (f"ESCALATION_{status}",)).fetchone()
    assert json.loads(details)["note"] == "fine"
    answered = next(e for e in after["escalations"] if e["escalation_id"] == budget["escalation_id"])
    assert answered["answer_note"] == "fine" and held["answer_note"] is None

    # answered once; an approval cannot be answered this way, and a budget request cannot be approved as a PO
    assert client.post(f"/api/runs/{run_id}/escalations/{budget['escalation_id']}/accept", json={}).status_code == 409
    assert client.post(f"/api/runs/{run_id}/escalations/{held['escalation_id']}/accept", json={}).status_code == 409
    assert client.post(f"/api/runs/{run_id}/escalations/{budget['escalation_id']}/approve", json={}).status_code == 409


def _race(client, run_id, esc_id, verbs):
    """The status codes of the same human decision sent by one thread per verb, released together."""
    barrier, codes = threading.Barrier(len(verbs)), {}

    def decide(i, verb):
        barrier.wait()
        codes[i] = client.post(f"/api/runs/{run_id}/escalations/{esc_id}/{verb}", json={"note": "n"}).status_code

    threads = [threading.Thread(target=decide, args=(i, v)) for i, v in enumerate(verbs)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return codes


@pytest.mark.parametrize("verbs", [("approve", "approve"), ("approve", "reject")])
def test_concurrent_decisions_have_exactly_one_winner(client, monkeypatch, verbs):
    real_submit = supplier.submit

    def slow_submit(conn, po_id):  # widens the window in which a second request could slip in
        time.sleep(0.05)
        return real_submit(conn, po_id)

    monkeypatch.setattr(supplier, "submit", slow_submit)
    for _ in range(10):
        use_script(monkeypatch, *S4_SCRIPT)
        run_id = start(client, "S4-BUDGET")
        read_events(client, run_id)
        esc = pending_escalation(client.get(f"/api/runs/{run_id}").json())
        codes = _race(client, run_id, esc["escalation_id"], verbs)
        assert sorted(codes.values()) == [200, 409]
        winner = verbs[next(i for i, c in codes.items() if c == 200)]

        db = sqlite3.connect(str(next(get_settings().runs_dir.glob(f"*{run_id}.db"))))
        logged = [a for (a,) in db.execute("SELECT action FROM audit_log WHERE actor = 'supplier_api' OR action LIKE 'PO_%'")
                  if a != "PO_CREATED"]
        status = db.execute("SELECT status FROM purchase_orders WHERE po_id = ?", (esc["po_id"],)).fetchone()[0]
        db.close()
        if winner == "approve":
            assert logged.count("PO_APPROVED") == 1 and "PO_REJECTED" not in logged
            assert status == "CONFIRMED" and logged.count("PO_CONFIRMED") == 1  # the supplier was called once
        else:
            assert logged == ["PO_REJECTED"] and status == "CANCELLED"


def test_unknown_ids_and_bad_bodies(client, monkeypatch):
    use_script(monkeypatch, *S4_SCRIPT)
    run_id = start(client, "S4-BUDGET")
    read_events(client, run_id)
    for url in ("/api/runs/20260101T000000-abcdef", "/api/runs/*", "/api/runs/nope/events"):
        assert client.get(url).status_code == 404
    assert client.post("/api/runs/nope/escalations/ESC-001/approve", json={}).status_code == 404
    assert client.post(f"/api/runs/{run_id}/escalations/ESC-999/approve", json={}).status_code == 404
    assert client.post("/api/runs", json={"scenario_id": "S9-NOPE"}).status_code == 404
    assert client.post("/api/runs", json={}).status_code == 422
    assert client.post(f"/api/runs/{run_id}/escalations/ESC-001/approve", json={"note": 5}).status_code == 422
    # an escalation that is not an approval (the budget request) cannot be approved
    budget = next(e for e in client.get(f"/api/runs/{run_id}").json()["escalations"] if e["kind"] == "BUDGET_INCREASE")
    assert client.post(f"/api/runs/{run_id}/escalations/{budget['escalation_id']}/approve", json={}).status_code == 409


def test_a_failed_run_is_reported_not_hidden(client, monkeypatch):
    use_script(monkeypatch, RuntimeError("provider down"))
    run_id = start(client)
    events, ended = read_events(client, run_id)
    assert ended and events[-1]["type"] == "run_finished" and events[-1]["data"]["outcome"] == "LLM_ERROR"
    s = client.get(f"/api/runs/{run_id}").json()
    assert s["outcome"] == "LLM_ERROR" and s["decision"] is None
    assert s["verification"]["passed"] is False and s["scorecard"]["passed"] is False
    assert any(e["kind"] == "INVESTIGATION" or e["status"] == "OPEN" for e in s["escalations"])  # the run was flagged
    flagged = [e for e in s["escalations"] if e["kind"] == "VERIFICATION_FAILED"]
    assert all(e["details"].get("findings") for e in flagged)  # the reason travels with the flag


def test_history_survives_a_server_restart(client, monkeypatch):
    use_script(monkeypatch, *S4_SCRIPT)
    run_id = start(client, "S4-BUDGET")
    events, _ = read_events(client, run_id)
    before = client.get(f"/api/runs/{run_id}").json()

    monkeypatch.setattr(registry, "REGISTRY", {})  # a new process knows nothing in memory
    assert client.get(f"/api/runs/{run_id}").json() == before
    assert read_events(client, run_id) == (events, True)
    monkeypatch.setattr(registry, "REGISTRY", {})
    assert [r["run_id"] for r in client.get("/api/runs").json()] == [run_id]
    esc = pending_escalation(before)
    assert client.post(f"/api/runs/{run_id}/escalations/{esc['escalation_id']}/approve", json={}).status_code == 200


def test_a_run_saved_before_phase_9_still_opens(client, monkeypatch):
    use_script(monkeypatch, *S1_SCRIPT)
    run_id = start(client)
    read_events(client, run_id)
    side = next(get_settings().runs_dir.glob(f"*__{run_id}.api.json"))
    saved = json.loads(side.read_text())
    card = saved["scorecard"]
    card["info_read_by_agent"] = card.pop("info_read")
    del card["repeat_reads"]
    side.write_text(json.dumps(saved))

    monkeypatch.setattr(registry, "REGISTRY", {})
    s = client.get(f"/api/runs/{run_id}").json()
    assert s["scorecard"]["info_read"] and s["scorecard"]["repeat_reads"] is None


def test_demo_mode_runs_end_to_end_with_a_baseline(client, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "baseline:rubber_stamp")
    assert client.get("/api/health").json() == {"ok": True, "model": "baseline:rubber_stamp", "local": True, "demo": True}

    run_id = start(client)
    events, ended = read_events(client, run_id)
    assert ended and events[-1]["type"] == "run_finished"
    s = client.get(f"/api/runs/{run_id}").json()
    assert s["model"] == "baseline:rubber_stamp" and s["decision"]["decision"] == "ACCEPT"
    assert s["scorecard"]["passed"] is False  # rubber-stamping S1-MODIFY is the wrong call

    monkeypatch.setenv("LLM_MODEL", "baseline:nonsense")
    r = client.post("/api/runs", json={"scenario_id": "S1-MODIFY"})
    assert r.status_code == 503 and "unknown baseline" in r.json()["detail"]


def test_unset_model_is_graceful(client):
    health = client.get("/api/health").json()
    assert health["ok"] is True and health["model"] == "" and health["demo"] is False
    r = client.post("/api/runs", json={"scenario_id": "S1-MODIFY"})
    assert r.status_code == 503 and "LLM_MODEL" in r.json()["detail"]


def test_eval_reports_use_the_contract_shape(client, tmp_path):
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    real = REAL_EVAL_DIR / "rubber_stamp.json"
    shutil.copy(real, eval_dir / "rubber_stamp.json")
    (eval_dir / "README.md").write_text("# not a run")
    (eval_dir / "notes.json").write_text('{"hello": 1}')
    (eval_dir / "broken.json").write_text("{")

    [report] = client.get("/api/eval").json()
    assert set(report) == {"name", "kind", "repeats", "temperature", "summary", "cards"}
    assert (report["name"], report["kind"]) == ("rubber_stamp", "baseline")
    s = report["summary"]
    assert set(s) == {"scenarios_passed", "scenarios", "runs_passed", "runs", "per_check"}
    assert s["runs"] == len(report["cards"]) and s["per_check"]["decision"] == [
        sum(c["checks"][0]["passed"] for c in report["cards"]), s["runs"]]
    assert client.get("/api/eval").status_code == 200 and not (tmp_path / "missing").exists()


def test_eval_reports_load_with_or_without_agent_version(client, tmp_path):
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    data = json.loads((REAL_EVAL_DIR / "rubber_stamp.json").read_text())
    data.pop("agent_version", None)
    (eval_dir / "old.json").write_text(json.dumps({**data, "name": "old"}))
    (eval_dir / "new.json").write_text(json.dumps({**data, "name": "new", "agent_version": {"git": None, "prompt_sha": "0" * 12}}))
    assert [r["name"] for r in client.get("/api/eval").json()] == ["new", "old"]


def test_eval_with_no_reports_is_empty(client):
    assert client.get("/api/eval").json() == []  # the directory does not even exist


def test_cors_allows_the_dev_server(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_frontend_files_and_spa_fallback(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "a.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    app = FastAPI()
    app.get("/api/ping")(lambda: {"ok": True})
    serve_frontend(app, dist)
    c = TestClient(app)

    assert c.get("/api/ping").json() == {"ok": True}
    assert c.get("/").text == "<html>app</html>" and c.get("/some/route").text == "<html>app</html>"
    assert c.get("/assets/a.js").text == "console.log(1)"
    assert c.get("/api/missing").status_code == 404
    assert c.get("/../secret.txt").text == "<html>app</html>"  # never leaves the dist folder


def test_create_app_serves_the_frontend_only_when_dist_exists(use_settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    use_settings(frontend_dist=dist)
    with_ui = TestClient(create_app())
    assert with_ui.get("/some/route").text == "<html>app</html>" and with_ui.get("/api/health").json()["ok"] is True
    assert with_ui.get("/api/missing").status_code == 404
    use_settings(frontend_dist=tmp_path / "absent")
    assert TestClient(create_app()).get("/some/route").status_code == 404
