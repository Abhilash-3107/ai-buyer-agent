"""The Literal types in the model-facing schemas must stay in step with the enums that own the vocabulary."""
from __future__ import annotations

import json
import sqlite3
from typing import get_args

from app.agent.tools import EscalateArgs
from app.agent.types import SubmitDecisionArgs
from app.purchasing.types import (
    AGENT_ESCALATION_KINDS,
    ActionStatus,
    PoStatus,
    Severity,
)
from app.scenarios.types import Decision


def _literal(model, field):
    return set(get_args(model.model_fields[field].annotation))


def test_decision_literal_matches_enum():
    assert _literal(SubmitDecisionArgs, "decision") == {d.value for d in Decision}


def test_escalation_kind_literal_matches_tuple():
    assert _literal(EscalateArgs, "kind") == set(AGENT_ESCALATION_KINDS)


def test_model_schema_has_no_enum_refs():
    assert "$defs" not in json.dumps(SubmitDecisionArgs.model_json_schema())
    assert "$defs" not in json.dumps(EscalateArgs.model_json_schema())


def test_str_enum_round_trips_through_sqlite_and_json():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (s TEXT)")
    conn.execute("INSERT INTO t VALUES (?)", (PoStatus.SUBMITTED,))
    assert conn.execute("SELECT s, typeof(s) FROM t").fetchone() == ("SUBMITTED", "text")
    assert json.dumps([ActionStatus.WRITTEN, Severity.ERROR]) == '["WRITTEN", "error"]'
