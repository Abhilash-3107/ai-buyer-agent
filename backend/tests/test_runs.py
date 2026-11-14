"""Per-run database files and the run's node."""
import sqlite3

import pytest

from app.agent import runs
from app.scenarios.catalog import SCENARIOS


def test_two_runs_get_two_files_with_their_own_run_id(tmp_path, use_settings):
    use_settings(runs_dir=tmp_path)
    (a, conn_a), (b, conn_b) = runs.new_run("S1-MODIFY"), runs.new_run("S1-MODIFY")
    assert a.path != b.path and a.run_id != b.run_id
    assert a.path.parent == tmp_path and a.path.name == f"S1-MODIFY__{a.run_id}.db"
    assert a.path.exists() and b.path.exists()
    for run, conn in ((a, conn_a), (b, conn_b)):
        assert conn.execute("SELECT value FROM meta WHERE key = 'run_id'").fetchone()[0] == run.run_id
    # the data really is separate: a write in one run is invisible in the other
    conn_a.execute("UPDATE inventory SET on_hand = 1")
    conn_a.commit()
    assert sqlite3.connect(b.path).execute("SELECT on_hand FROM inventory").fetchone()[0] == 220


def test_in_memory_run_writes_no_file(tmp_path, use_settings):
    use_settings(runs_dir=tmp_path)
    run, conn = runs.new_run("S1-MODIFY", in_memory=True)
    assert list(tmp_path.iterdir()) == []
    assert conn.execute("SELECT value FROM meta WHERE key = 'run_id'").fetchone()[0] == run.run_id


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_node_comes_from_the_trigger(sid):
    """Covers all three trigger types: recommendation row, supplier event's PO, and the alert itself."""
    run, _ = runs.new_run(sid, in_memory=True)
    assert run.node_id == "DS-NORTH" and run.scenario_id == sid


def test_node_is_derived_from_the_data_not_hard_coded():
    _, conn = runs.new_run("S1-MODIFY", in_memory=True)
    conn.execute("UPDATE recommendations SET node_id = 'DS-SOUTH'")
    assert runs._trigger_node(conn, SCENARIOS["S1-MODIFY"].trigger) == "DS-SOUTH"
    _, conn = runs.new_run("S2-SOURCE-ELSEWHERE", in_memory=True)
    conn.execute("UPDATE purchase_orders SET node_id = 'DS-SOUTH' WHERE po_id = 'PO-2001'")
    assert runs._trigger_node(conn, SCENARIOS["S2-SOURCE-ELSEWHERE"].trigger) == "DS-SOUTH"
