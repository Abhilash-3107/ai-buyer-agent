"""The trace: ordered JSONL events and a live callback that sees the same ones."""
import itertools
import json

from scripted import call, reply, scripted_llm, submit

from app import runs
from app.agent import run_agent
from app.trace import Trace


def test_events_are_written_in_order_and_pushed_to_the_callback(tmp_path):
    seen = []
    trace = Trace(tmp_path / "t.jsonl", on_event=seen.append)
    trace.emit("run_started", 0, scenario_id="X")
    trace.emit("tool_call", 1, name="get_budget", args={"sku": "S"}, by="agent")
    trace.emit("run_finished", 1, outcome="DECIDED")

    lines = [json.loads(line) for line in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert [line["seq"] for line in lines] == [1, 2, 3]
    assert lines == [{"seq": e.seq, "turn": e.turn, "type": e.type, "data": e.data, "ts": e.ts} for e in seen]
    assert all(a["ts"] <= b["ts"] for a, b in itertools.pairwise(lines))


def test_without_a_path_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen = []
    Trace(None, on_event=seen.append).emit("error", 0, message="x")
    assert len(seen) == 1 and list(tmp_path.iterdir()) == []


def test_a_run_writes_its_trace_next_to_its_database(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    seen = []
    result = run_agent("S3-ONE-OFF-SPIKE", scripted_llm([reply(submit("ACCEPT", 0, 30.0))]), on_event=seen.append)
    assert result.trace_path == tmp_path / f"S3-ONE-OFF-SPIKE__{result.run.run_id}.trace.jsonl"
    assert result.run.path.parent == result.trace_path.parent
    lines = [json.loads(line) for line in result.trace_path.read_text().splitlines()]
    assert [line["seq"] for line in lines] == list(range(1, len(lines) + 1))
    assert [line["type"] for line in lines] == [e.type for e in seen]


def test_an_in_memory_run_has_no_trace_file():
    result = run_agent("S3-ONE-OFF-SPIKE", scripted_llm([reply(submit("ACCEPT", 0, 30.0))]), in_memory=True)
    assert result.trace_path is None


def test_trace_lines_are_strict_json_even_for_infinite_model_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    script = [reply(call("get_budget", '{"sku": "SKU-1002", "a": Infinity, "b": [-Infinity, NaN]}')),
              reply(submit("ACCEPT", 0, 30.0))]
    seen = []
    result = run_agent("S3-ONE-OFF-SPIKE", scripted_llm(script), on_event=seen.append)

    def reject(constant):
        raise AssertionError(f"non-strict JSON constant {constant}")

    lines = [json.loads(line, parse_constant=reject) for line in result.trace_path.read_text().splitlines()]
    sent = next(line for line in lines if line["type"] == "tool_call" and line["data"]["by"] == "agent")
    assert sent["data"]["args"] == {"sku": "SKU-1002", "a": "infinite", "b": ["-infinite", "nan"]}
