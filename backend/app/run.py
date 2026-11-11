"""CLI: run the agent on one scenario and print the trace, then the decision and the verifier's verdict.

    uv run python -m app.run S1-MODIFY
"""
from __future__ import annotations

import sys

from .agent import run_agent
from .llm import LLMClient
from .scenarios import SCENARIOS
from .trace import TraceEvent


def _short(value: object, limit: int = 110) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def summary(e: TraceEvent) -> str:
    d = e.data
    if e.type == "run_started":
        return f"{d['scenario_id']} run {d['run_id']} at {d['node_id']} for {d['sku']}"
    if e.type == "llm_response":
        calls = ", ".join(c["name"] for c in d["tool_calls"]) or "text only"
        return f"{calls} ({d['latency_s']}s) {_short(d['text'] or '', 60)}".rstrip()
    if e.type == "tool_call":
        return f"{d['by']}: {d['name']} {_short(d['args'])}"
    if e.type == "tool_result":
        r = d["result"]
        return f"{d['name']} ok={d['ok']} {_short(r.get('error') or r.get('message') or r.get('status') or '')}"
    if e.type == "nudge":
        return f"nudge {d['count']}"
    if e.type == "recovered_tool_call":
        return f"{d['name']} recovered from text {_short(d['args'])}"
    if e.type == "flagged":
        return f"escalation {d['escalation_id']}: {_short(', '.join(d['findings']))}"
    if e.type == "budget_locked":
        return f"writes locked after repeated failure {d['key']}"
    if e.type == "decision":
        return f"{d['decision']} new_units={d['new_units']} demand={d['daily_demand_used']}"
    if e.type == "verification":
        return f"round {d['round']}: " + ("passed" if d["passed"] else ", ".join(f["code"] for f in d["findings"]))
    if e.type == "run_finished":
        return f"{d['outcome']} in {d['steps']} turns, {d['tokens_in']}+{d['tokens_out']} tokens, {d['latency_s']}s"
    return _short(d.get("message", d))


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in SCENARIOS:
        print("usage: uv run python -m app.run <scenario id>\n" + "\n".join(f"  {s}" for s in SCENARIOS))
        return 2
    result = run_agent(argv[0], LLMClient(),
                       on_event=lambda e: print(f"{e.seq:>3} t{e.turn:<2} {e.type:<14} {summary(e)}", flush=True))
    d = result.decision
    print(f"\nOutcome:  {result.outcome}")
    if d:
        print(f"Decision: {d.decision}, new_units={d.new_units}, confidence={d.confidence}\n  {d.summary}")
    v = result.verification
    print("Verifier: " + ("PASSED" if v.passed else "FAILED"))
    for f in v.findings:
        print(f"  {f.code}: {f.message}")
    print(f"Trace:    {result.trace_path or '(in memory)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
