"""CLI: run scenarios x repeats for a model or a baseline, score every run, write a JSON file and a Markdown report.

    uv run python -m app.evaluate --model qwen2.5:7b --repeats 3
    uv run python -m app.evaluate --baseline rubber_stamp
    uv run python -m app.evaluate --model qwen2.5:7b --scenarios S1-MODIFY,S2-ALT-ALSO-SHORT
    uv run python -m app.evaluate --compare ../docs/eval/*.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from statistics import fmean

from .agent import run_agent
from .baselines import BASELINES, BaselineClient
from .llm import LLMClient, LLMConfig
from .prompts import SYSTEM_PROMPT
from .scenarios import SCENARIOS
from .scoring import CHECK_NAMES, ScoreCard, score_run

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "docs" / "eval"


def evaluate(name: str, make_client, scenario_ids: list[str], repeats: int, *, log=print,
             on_card=None) -> list[ScoreCard]:
    """One fresh client and one fresh run database per run; the connection is closed once the run is scored.
    `on_card(cards)` is called after every finished run, so a caller can save partial results."""
    cards = []
    for scenario_id in scenario_ids:
        for repeat in range(1, repeats + 1):
            result = run_agent(scenario_id, make_client())
            try:
                card = score_run(SCENARIOS[scenario_id], result, model=name)
            finally:
                result.conn.close()
            cards.append(card)
            if on_card:
                on_card(cards)
            log(f"{scenario_id} repeat {repeat}/{repeats} {card.outcome} {'passed' if card.passed else 'FAILED'} "
                f"{card.latency_s:.1f}s")
    return cards


# --- summary -------------------------------------------------------------------------------------
def _by_scenario(cards: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for c in cards:
        grouped.setdefault(c["scenario_id"], []).append(c)
    return grouped


def _check(card: dict, name: str) -> dict:
    return next(c for c in card["checks"] if c["name"] == name)


def summarize(cards: list[dict]) -> dict:
    """Headline numbers from score cards (as dicts, so a saved JSON file summarizes the same way)."""
    grouped = _by_scenario(cards)
    rates = {}
    for name in CHECK_NAMES:
        checks = [_check(c, name) for c in cards if _check(c, name)["applicable"]]
        rates[name] = (sum(c["passed"] for c in checks), len(checks))
    return {
        "runs": len(cards), "runs_passed": sum(c["passed"] for c in cards),
        "scenarios": len(grouped), "scenarios_passed": sum(all(c["passed"] for c in g) for g in grouped.values()),
        "check_rates": rates,
        "mean_turns": fmean(c["turns"] for c in cards), "mean_tool_calls": fmean(c["tool_calls"] for c in cards),
        "mean_blocked_writes": fmean(c["blocked_writes"] for c in cards),
        "mean_tokens_in": fmean(c["tokens_in"] for c in cards), "mean_tokens_out": fmean(c["tokens_out"] for c in cards),
        "mean_latency_s": fmean(c["latency_s"] for c in cards), "total_latency_s": sum(c["latency_s"] for c in cards),
        "outcomes": dict(Counter(c["outcome"] for c in cards)),
    }


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
    for scenario_id, group in _by_scenario(cards).items():
        exp = SCENARIOS[scenario_id].expected
        decisions = Counter(c["decision"] or "none" for c in group)
        got, k = decisions.most_common(1)[0]
        band = f"{exp.new_buy_qty[0]}-{exp.new_buy_qty[1]}"
        units = ", ".join(str(c["new_buy_units"]) for c in group)
        lines.append(f"| {scenario_id} | {exp.decision} | {got} | {units} ({band}) | "
                     + " | ".join(_mark([_check(c, n) for c in group]) for n in CHECK_NAMES) + f" | {k}/{len(group)} | "
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
            group = _by_scenario(e["cards"]).get(scenario_id, [])
            row.append(f"{sum(c['passed'] for c in group)}/{len(group)}" if group else "-")
        lines.append(f"| {scenario_id} | " + " | ".join(row) + " |")
    return "\n".join(lines + [""])


# --- CLI -----------------------------------------------------------------------------------------
def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name)


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=Path(__file__).resolve().parent, capture_output=True, text=True,
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
        target = out / f"{_slug(name)}{suffix}"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, target)  # atomic: an interrupted run never leaves a half-written file


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m app.evaluate", description=__doc__.split("\n\n")[0])
    p.add_argument("--model", help="model name; overrides LLM_MODEL (base url and key come from the environment)")
    p.add_argument("--baseline", choices=sorted(BASELINES), help="run a non-LLM baseline instead of a model")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--scenarios", help="comma-separated scenario ids (default: all)")
    p.add_argument("--compare", nargs="+", type=Path, metavar="JSON", help="write one comparison table from saved results")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory (default: <repo>/docs/eval)")
    args = p.parse_args(argv)

    if args.compare:
        evals = [json.loads(f.read_text()) for f in sorted(args.compare)]
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "README.md").write_text(render_comparison(evals))
        print(f"wrote {args.out / 'README.md'}")
        return 0

    ids = args.scenarios.split(",") if args.scenarios else list(SCENARIOS)
    unknown = [i for i in ids if i not in SCENARIOS]
    if unknown or args.repeats < 1:
        p.error(f"unknown scenario(s) {unknown}" if unknown else "--repeats must be at least 1")

    if args.baseline:
        name, kind, temperature = args.baseline, "baseline", None
        def make_client():
            return BaselineClient(args.baseline)
    else:
        env = LLMConfig.from_env()
        config = replace(env, model=args.model or env.model, temperature=0.0 if env.temperature is None else env.temperature)
        name, kind, temperature = config.model, "model", config.temperature
        def make_client():
            return LLMClient(config)
    version = agent_version()  # taken once, when the run starts
    evaluate(name, make_client, ids, args.repeats, log=lambda m: print(m, flush=True),
             on_card=lambda done: write_eval(args.out, name, kind, done, args.repeats, temperature, version))
    print(f"wrote {args.out / _slug(name)}.json and .md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
