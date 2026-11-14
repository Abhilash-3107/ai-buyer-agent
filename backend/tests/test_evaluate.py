"""Baselines through the real pipeline, and the report writer driven by the scripted fake model (no real LLM)."""
import hashlib
import json
import re

import pytest
from scripted import call, investigate, reply, scripted_llm, submit

from app import evaluate as evaluate_module
from app.baselines import BaselineClient
from app.evaluate import evaluate, main, write_eval
from app.prompts import SYSTEM_PROMPT
from app.scenarios import SCENARIOS
from app.scoring import CHECK_NAMES

S1 = {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "daily_demand": 40, "reason": "r"}


@pytest.fixture(autouse=True)
def runs_in_tmp(use_settings):
    use_settings()


def baseline_cards(name):
    return evaluate(name, lambda: BaselineClient(name), list(SCENARIOS), 1, log=lambda m: None)


def test_do_nothing_passes_nothing_and_on_a_reject_only_misses_the_investigation():
    cards = baseline_cards("do_nothing")
    assert not any(c.passed for c in cards)
    wanted = {s.id for s in SCENARIOS.values()
              if s.expected.decision == "REJECT" and s.expected.new_buy_qty == (0, 0) and s.expected.escalation is None}
    right = {c.scenario_id for c in cards
             if [ch.name for ch in c.checks if ch.applicable and not ch.passed] == ["information"]}
    assert right == wanted and right


def test_rubber_stamp_runs_everything_and_fails_s1_modify():
    cards = {c.scenario_id: c for c in baseline_cards("rubber_stamp")}
    assert set(cards) == set(SCENARIOS) and all(c.outcome == "DECIDED" for c in cards.values())
    assert not cards["S1-MODIFY"].passed and cards["S1-MODIFY"].new_buy_units == 0  # the engine's 800 is blocked
    assert sum(c.passed for c in cards.values()) < len(cards) // 2


def scripted_client_factory():
    scripts = {"good": [investigate("SKU-1002"), reply(call("get_budget", {"sku": "SKU-1002"})),
                        reply(call("create_po", {**S1, "qty": 192})), reply(submit("MODIFY", 192))],
               "bad": [reply(submit("REJECT", 0, demand=None)), reply(submit("REJECT", 0, demand=None))]}
    order = iter(["good", "bad"])
    return lambda: scripted_llm(scripts[next(order)])


def test_report_has_every_check_and_a_failure_reason(tmp_path):
    cards = evaluate("scripted", scripted_client_factory(), ["S1-MODIFY", "S1-ACCEPT"], 1, log=lambda m: None)
    write_eval(tmp_path, "scripted", "model", cards, 1, 0.0)

    data = json.loads((tmp_path / "scripted.json").read_text(), parse_constant=lambda c: pytest.fail(f"non-strict {c}"))
    assert [c["scenario_id"] for c in data["cards"]] == ["S1-MODIFY", "S1-ACCEPT"]
    assert [c["passed"] for c in data["cards"]] == [True, False]
    report = (tmp_path / "scripted.md").read_text()
    assert all(name in report for name in CHECK_NAMES)
    assert "## Why it failed" in report and "decided REJECT, expected ACCEPT" in report and data["cards"][1]["run_id"] in report
    assert "\u2013" not in report and "\u2014" not in report


def test_report_records_the_agent_version(tmp_path):
    cards = evaluate("scripted", scripted_client_factory(), ["S1-MODIFY"], 1, log=lambda m: None)
    write_eval(tmp_path, "scripted", "model", cards, 1, 0.0)
    version = json.loads((tmp_path / "scripted.json").read_text())["agent_version"]
    assert set(version) == {"git", "prompt_sha"}
    assert version["prompt_sha"] == hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12]
    assert version["git"] is None or re.fullmatch(r"[0-9a-f]{4,}(-dirty)?", version["git"])
    assert f"Agent version: git {version['git'] or 'unknown'}, prompt {version['prompt_sha']}." in (tmp_path / "scripted.md").read_text()


def test_agent_version_marks_a_dirty_tree_and_survives_missing_git(monkeypatch):
    answers = {"rev-parse": "abc1234", "status": " M app/agent.py"}
    monkeypatch.setattr(evaluate_module, "_git", lambda *a: answers[a[0]])
    assert evaluate_module.agent_version()["git"] == "abc1234-dirty"
    answers["status"] = ""
    assert evaluate_module.agent_version()["git"] == "abc1234"
    monkeypatch.setattr(evaluate_module, "_git", lambda *a: None)
    assert evaluate_module.agent_version()["git"] is None


def test_older_reports_without_agent_version_still_render_and_compare(tmp_path):
    cards = evaluate("scripted", scripted_client_factory(), ["S1-MODIFY"], 1, log=lambda m: None)
    write_eval(tmp_path, "old", "model", cards, 1, 0.0)
    data = json.loads((tmp_path / "old.json").read_text())
    del data["agent_version"]
    (tmp_path / "old.json").write_text(json.dumps(data))
    assert "Agent version" not in evaluate_module.render_report("old", data["cards"], 1)
    assert main(["--compare", str(tmp_path / "old.json"), "--out", str(tmp_path)]) == 0
    assert "old" in (tmp_path / "README.md").read_text()


def test_cli_baseline_then_compare(tmp_path):
    for name in ("rubber_stamp", "do_nothing"):
        assert main(["--baseline", name, "--scenarios", "S1-REJECT,S1-MODIFY", "--out", str(tmp_path)]) == 0
    assert main(["--compare", *map(str, tmp_path.glob("*.json")), "--out", str(tmp_path)]) == 0
    table = (tmp_path / "README.md").read_text()
    assert "do_nothing" in table and "rubber_stamp" in table and "S1-REJECT" in table


def test_report_counts_repeat_reads(tmp_path):
    cards = evaluate("scripted", scripted_client_factory(), ["S1-MODIFY", "S1-ACCEPT"], 1, log=lambda m: None)
    write_eval(tmp_path, "scripted", "model", cards, 1, 0.0)
    report = (tmp_path / "scripted.md").read_text()
    assert "Repeat reads" in report and "preload" not in report
    rows = {line.split(" | ")[0].lstrip("| "): line for line in report.splitlines() if line.startswith("| S1-")}
    assert rows["S1-MODIFY"].endswith("| 1 |") and rows["S1-ACCEPT"].endswith("| 0 |")  # the good run read the budget twice


def test_results_are_written_after_every_finished_run(tmp_path, monkeypatch):
    seen = []
    real = evaluate_module.write_eval

    def spy(out, *args):
        real(out, *args)
        seen.append(len(json.loads((out / "do_nothing.json").read_text())["cards"]))
        assert (out / "do_nothing.md").exists() and not list(out.glob("*.tmp"))

    monkeypatch.setattr(evaluate_module, "write_eval", spy)
    assert main(["--baseline", "do_nothing", "--scenarios", "S1-REJECT,S1-MODIFY", "--repeats", "2", "--out", str(tmp_path)]) == 0
    assert seen == [1, 2, 3, 4]
