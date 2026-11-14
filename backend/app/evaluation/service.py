"""Run scenarios x repeats through an agent, score every run and summarize the cards."""
from __future__ import annotations

from collections import Counter
from statistics import fmean

from ..agent.service import run_agent
from ..scenarios.catalog import SCENARIOS
from .scoring import score_run
from .types import CHECK_NAMES, ScoreCard


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
def by_scenario(cards: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for c in cards:
        grouped.setdefault(c["scenario_id"], []).append(c)
    return grouped


def check_named(card: dict, name: str) -> dict:
    return next(c for c in card["checks"] if c["name"] == name)


def summarize(cards: list[dict]) -> dict:
    """Headline numbers from score cards (as dicts, so a saved JSON file summarizes the same way)."""
    grouped = by_scenario(cards)
    rates = {}
    for name in CHECK_NAMES:
        checks = [check_named(c, name) for c in cards if check_named(c, name)["applicable"]]
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
