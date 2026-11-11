"""The CLI shares the API's client factory, so demo mode works without an API key."""
from app import run, runs


def test_cli_demo_mode_runs_without_a_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("LLM_MODEL", "baseline:rubber_stamp")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert run.main(["S1-REJECT"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("DEMO: baseline policy 'rubber_stamp'")
    assert "not the agent" in out.splitlines()[0]
    assert "Verifier:" in out
