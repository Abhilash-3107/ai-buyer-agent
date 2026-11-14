"""Markdown reports and comparison tables for evaluation results, and the files they are written to."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from ..agent.prompts import SYSTEM_PROMPT
from ..scenarios.catalog import SCENARIOS
from .service import by_scenario, check_named, summarize
from .types import CHECK_NAMES, ScoreCard


def _pct(passed: int, total: int) -> str:
    return f"{passed}/{total} ({passed / total:.0%})" if total else "n/a"


# --- Markdown ------------------------------------------------------------------------------------
def _mark(checks: list[dict]) -> str:
    applicable = [c["passed"] for c in checks if c["applicable"]]
    if not applicable:
        return "-"
    return "✓" if all(applicable) else "✗" if not any(applicable) else f"{sum(applicable)}/{len(applicable)}"


def _version_line(agent_version: dict | None) -> list[str]:
    if not agent_version:
        return []
    return [f"Agent version: git {agent_version.get('git') or 'unknown'}, prompt {agent_version.get('prompt_sha') or 'unknown'}.", ""]


def render_report(name: str, cards: list[dict], repeats: int, agent_version: dict | None = None) -> str:
    s = summarize(cards)
    lines = [f"# Evaluation: {name}", "", *_version_line(agent_version),
             "Every score is a deterministic check on the final database and the tool calls, with its reason written next to it.",
             f"{s['runs']} runs: {s['scenarios']} scenarios x {repeats} repeat(s).", "",
             "## Headline", "",
             f"- Scenarios passed (every repeat passed): **{s['scenarios_passed']}/{s['scenarios']}**",
             f"- Runs passed: **{_pct(s['runs_passed'], s['runs'])}**",
             f"- Run outcomes: {', '.join(f'{k} x{v}' for k, v in sorted(s['outcomes'].items()))}", "",
             "| Check | Passed |", "|---|---|"]
    lines += [f"| {n} | {_pct(*s['check_rates'][n])} |" for n in CHECK_NAMES]

    lines += ["", "## Scenarios", "",
              "A check shows ✓ when every repeat passed, ✗ when none did, k/n when mixed, and - when it did not apply.",
              "Consistency is how many runs gave the most common decision.",
              "Repeat reads counts, per run, the reads that repeated an earlier successful read with the same arguments.", "",
              "| Scenario | Expected | Got | New units (band) | " + " | ".join(CHECK_NAMES) + " | Consistency | Repeat reads |",
              "|---|---|---|---|" + "---|" * len(CHECK_NAMES) + "---|---|"]
    for scenario_id, group in by_scenario(cards).items():
        exp = SCENARIOS[scenario_id].expected
        decisions = Counter(c["decision"] or "none" for c in group)
        got, k = decisions.most_common(1)[0]
        band = f"{exp.new_buy_qty[0]}-{exp.new_buy_qty[1]}"
        units = ", ".join(str(c["new_buy_units"]) for c in group)
        lines.append(f"| {scenario_id} | {exp.decision} | {got} | {units} ({band}) | "
                     + " | ".join(_mark([check_named(c, n) for c in group]) for n in CHECK_NAMES) + f" | {k}/{len(group)} | "
                     + ", ".join(str(c.get("repeat_reads", "-")) for c in group) + " |")

    lines += ["", "## Why it failed", ""]
    failures = [(c, ch) for c in cards for ch in c["checks"] if ch["applicable"] and not ch["passed"]]
    if not failures:
        lines.append("No check failed.")
    for c, ch in failures:
        lines.append(f"- {c['scenario_id']}, run {c['run_id']}, {ch['name']}: {ch['reason']}")

    lines += ["", "## Cost and speed", "",
              f"- Mean turns per run: {s['mean_turns']:.1f}",
              f"- Mean tool calls chosen by the agent: {s['mean_tool_calls']:.1f}",
              f"- Mean blocked or unjustified writes: {s['mean_blocked_writes']:.2f}",
              f"- Mean tokens per run: {s['mean_tokens_in']:.0f} in, {s['mean_tokens_out']:.0f} out",
              f"- Mean latency per run: {s['mean_latency_s']:.1f}s (total {s['total_latency_s']:.0f}s)", ""]
    return "\n".join(lines)


def render_comparison(evals: list[dict]) -> str:
    """One table with every model and baseline side by side, then a per-scenario matrix."""
    lines = ["# Evaluation comparison", "",
             "Each row is one evaluated model or baseline, scored by the same code on the same scenarios.",
             "The baselines are deliberately dumb: if they scored well, the eval would be broken.", "",
             "| Name | Kind | Runs | Scenarios passed | Runs passed | " + " | ".join(CHECK_NAMES)
             + " | Mean turns | Mean latency |", "|---|---|---|---|---|" + "---|" * len(CHECK_NAMES) + "---|---|"]
    for e in evals:
        s = summarize(e["cards"])
        lines.append(f"| {e['name']} | {e['kind']} | {s['runs']} | {s['scenarios_passed']}/{s['scenarios']} | "
                     f"{_pct(s['runs_passed'], s['runs'])} | "
                     + " | ".join(_pct(*s["check_rates"][n]) for n in CHECK_NAMES)
                     + f" | {s['mean_turns']:.1f} | {s['mean_latency_s']:.1f}s |")
    lines += ["", "## Runs passed per scenario", "",
              "| Scenario | " + " | ".join(e["name"] for e in evals) + " |", "|---|" + "---|" * len(evals)]
    for scenario_id in SCENARIOS:
        row = []
        for e in evals:
            group = by_scenario(e["cards"]).get(scenario_id, [])
            row.append(f"{sum(c['passed'] for c in group)}/{len(group)}" if group else "-")
        lines.append(f"| {scenario_id} | " + " | ".join(row) + " |")
    return "\n".join(lines + [""])


# --- Files ---------------------------------------------------------------------------------------
def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name)


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                              timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip()


def agent_version() -> dict:
    """Which agent produced a report: the git commit (marked -dirty when the code has uncommitted changes) and a
    hash of the system prompt. Reports saved before this field existed simply lack it."""
    sha = _git("rev-parse", "--short", "HEAD")
    if sha:
        # the reports this very run writes under docs/eval must not make the tree look dirty
        changed = _git("status", "--porcelain", "--", ".", ":(top,exclude)docs/eval")
        if changed is None:
            sha = None
        elif changed:
            sha += "-dirty"
    return {"git": sha or None, "prompt_sha": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12]}


def write_eval(out: Path, name: str, kind: str, cards: list[ScoreCard], repeats: int, temperature: float | None,
               version: dict | None = None) -> None:
    version = version or agent_version()
    data = {"name": name, "kind": kind, "repeats": repeats, "temperature": temperature, "agent_version": version,
            "cards": [asdict(c) for c in cards]}
    out.mkdir(parents=True, exist_ok=True)
    for suffix, text in ((".json", json.dumps(data, indent=2, allow_nan=False) + "\n"),
                         (".md", render_report(name, data["cards"], repeats, version))):
        target = out / f"{slug(name)}{suffix}"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, target)  # atomic: an interrupted run never leaves a half-written file
