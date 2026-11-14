"""Real model, real wiring. Skipped unless LLM_LIVE=1; decision quality is judged in Phase 5, not here."""
import os

import pytest

from app.agent import run_agent
from app.config import load_env
from app.llm import LLMClient, LLMConfig
from app.scenarios import SCENARIOS

load_env()
pytestmark = pytest.mark.skipif(os.getenv("LLM_LIVE") != "1", reason="set LLM_LIVE=1 to call the configured model")


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_every_scenario_runs_to_an_outcome_with_a_trace(sid):
    result = run_agent(sid, LLMClient(LLMConfig.from_env()))
    assert result.outcome in ("DECIDED", "MAX_STEPS")
    assert result.trace_path is not None and result.trace_path.exists()
