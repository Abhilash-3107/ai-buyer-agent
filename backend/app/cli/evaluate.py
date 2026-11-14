"""CLI: run scenarios x repeats for a model or a baseline, score every run, write a JSON file and a Markdown report.

    uv run python -m app.cli.evaluate --model buyer-qwen3.5-4b --repeats 3
    uv run python -m app.cli.evaluate --model <openai-model> --repeats 3
    uv run python -m app.cli.evaluate --baseline rubber_stamp
    uv run python -m app.cli.evaluate --model buyer-qwen3.5-4b --scenarios S1-MODIFY,S2-ALT-ALSO-SHORT
    uv run python -m app.cli.evaluate --compare ../docs/eval/*.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from ..agent.llm import LLMClient, LLMConfig
from ..config import get_settings, load_env
from ..evaluation.baselines import BASELINES, BaselineClient
from ..evaluation.report import agent_version, render_comparison, slug, write_eval
from ..evaluation.service import evaluate
from ..scenarios.catalog import SCENARIOS


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    load_env()
    p = argparse.ArgumentParser(prog="python -m app.cli.evaluate", description=__doc__.split("\n\n")[0])
    p.add_argument("--model", help="model name; overrides LLM_MODEL (base url and key come from the environment)")
    p.add_argument("--baseline", choices=sorted(BASELINES), help="run a non-LLM baseline instead of a model")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--scenarios", help="comma-separated scenario ids (default: all)")
    p.add_argument("--compare", nargs="+", type=Path, metavar="JSON", help="write one comparison table from saved results")
    p.add_argument("--out", type=Path, default=None, help="output directory (default: <repo>/docs/eval)")
    args = p.parse_args(argv)
    args.out = args.out or get_settings().eval_dir

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
        if not config.model:
            p.error("no model: pass --model or set LLM_MODEL")
        name, kind, temperature = config.model, "model", config.temperature
        def make_client():
            return LLMClient(config)
    version = agent_version()  # taken once, when the run starts
    evaluate(name, make_client, ids, args.repeats, log=lambda m: print(m, flush=True),
             on_card=lambda done: write_eval(args.out, name, kind, done, args.repeats, temperature, version))
    print(f"wrote {args.out / slug(name)}.json and .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
