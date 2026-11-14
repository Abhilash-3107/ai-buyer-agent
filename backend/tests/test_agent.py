"""The agent loop with a scripted model: happy path, both feedback loops, robustness and every limit."""
import itertools
import json

from scripted import call, reply, scripted_llm, submit

from app.agent.service import run_agent

S1 = {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "daily_demand": 40, "reason": "r"}
S2 = {"sku": "SKU-2003", "daily_demand": 40, "reason": "r"}


def run(script, scenario="S1-MODIFY", **kw):
    events = []
    result = run_agent(scenario, scripted_llm(script), in_memory=True, on_event=events.append, **kw)
    return result, events


def results(events, name):
    return [e.data["result"] for e in events if e.type == "tool_result" and e.data["name"] == name]


def escalations(result):
    return [r["kind"] for r in result.conn.execute("SELECT kind FROM escalations")]


def test_s1_modify_happy_path():
    script = [
        reply(call("plan_order", {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "daily_demand": 40})),
        reply(call("create_po", {**S1, "qty": 800})),
        reply(call("create_po", {**S1, "qty": 192})),
        reply(submit("MODIFY", 192)),
    ]
    result, events = run(script)

    assert result.outcome == "DECIDED" and result.verification.passed and result.decision.decision == "MODIFY"
    assert result.steps == 4 and (result.tokens_in, result.tokens_out) == (400, 40)
    # nothing is read before the first model call: every tool call is the model's (D61)
    assert not [e for e in events if e.turn == 0 and e.type in ("tool_call", "tool_result")]
    assert all(e.data["by"] == "agent" for e in events if e.type == "tool_call")
    agent_calls = [e.data["name"] for e in events if e.type == "tool_call" and e.data["by"] == "agent"]
    assert agent_calls == ["plan_order", "create_po", "create_po", "submit_decision"]
    assert [r["status"] for r in results(events, "create_po")] == ["BLOCKED", "WRITTEN"]
    assert [c.name for c in result.tool_calls] == ["plan_order", "create_po", "create_po"]
    types = [e.type for e in events]
    assert types[0] == "run_started" and types[-1] == "run_finished"
    assert types.index("decision") < types.index("verification") < types.index("run_finished")
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


def test_trace_records_what_the_model_was_sent_and_which_harness_steps_ran():
    script = [
        reply(call("create_po", {**S1, "qty": 800}, "c1")),
        reply(call("create_po", {**S1, "qty": 192}, "c2")),
        reply(call("submit_decision", submit("MODIFY", 192)[1], "c3")),
    ]
    llm = scripted_llm(script)
    events = []
    run_agent("S1-MODIFY", llm, in_memory=True, on_event=events.append)

    requests = [e for e in events if e.type == "llm_request"]
    assert [e.turn for e in requests] == [1, 2, 3]
    first, second = requests[0].data, requests[1].data
    assert [m["role"] for m in first["messages"]] == ["system", "user"] and first["message_count"] == 2
    assert len(first["tools"]) == 18 and "tools" not in second  # the tool list is recorded once
    assert [m["role"] for m in second["messages"]] == ["assistant", "tool"] and second["message_count"] == 4
    assert second["messages"][1] == llm.sent[1][-1]  # exactly what the model received
    assert all(e.data["model"] == "scripted" for e in events if e.type == "llm_response")

    steps = [(e.data["call_id"], e.data["stage"], e.data["status"]) for e in events if e.type == "harness_step"]
    assert steps == [("c1", "request", "ACCEPTED"), ("c1", "validator", "BLOCKED"),
                     ("c2", "request", "ACCEPTED"), ("c2", "validator", "PASSED"),
                     ("c2", "approval", "AUTO_SUBMITTED"), ("c2", "supplier", "CONFIRMED"),
                     ("c3", "request", "ACCEPTED")]
    supplier = next(e.data for e in events if e.type == "harness_step" and e.data["stage"] == "supplier")
    assert (supplier["requested"], supplier["confirmed"]) == (192, 192)


def test_harness_steps_never_reach_the_model_or_the_traced_result():
    llm = scripted_llm([reply(call("create_po", {**S1, "qty": 192}, "c1")), reply(submit("MODIFY", 192))])
    events = []
    run_agent("S1-MODIFY", llm, in_memory=True, on_event=events.append)

    tool_message = llm.sent[1][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "c1"
    assert "harness_steps" not in json.loads(tool_message["content"])
    assert any(e.type == "harness_step" for e in events)
    assert "harness_steps" not in results(events, "create_po")[0]
    assert [k for k in json.loads(tool_message["content"])] == [
        "ok", "status", "po_id", "escalation_id", "message", "violations", "shortfall", "supplier"]


def request_steps(events):
    return [(e.data["call_id"], e.data["status"], e.data["detail"]) for e in events
            if e.type == "harness_step" and e.data["stage"] == "request"]


def test_every_agent_call_gets_a_request_step_before_its_write_steps():
    result, events = run([reply(call("create_po", {**S1, "qty": 192}, "w1"), call("get_budget", {"sku": "SKU-1002"}, "r1")),
                          reply(call("submit_decision", submit("MODIFY", 192)[1], "s1"))])
    assert request_steps(events) == [(c, "ACCEPTED", "Known tool, arguments valid") for c in ("w1", "r1", "s1")]
    assert [(e.data["call_id"], e.data["stage"]) for e in events if e.type == "harness_step"][:4] == [
        ("w1", "request"), ("w1", "validator"), ("w1", "approval"), ("w1", "supplier")]
    assert all(e.data.get("call_id") for e in events if e.type == "harness_step")  # none for the harness's own reads
    assert result.outcome == "DECIDED"


def test_rejected_and_locked_requests_are_traced_and_nothing_runs():
    blocked = [call("create_po", {**S1, "qty": 800}, f"b{i}") for i in (1, 2, 3)]
    script = [reply(*blocked),
              reply(call("buy_everything", {}, "u"), call("get_budget", {}, "i"), call("get_budget", '{"sku": ', "m"),
                    call("create_po", {**S1, "qty": 192}, "l"), call("submit_decision", {"decision": "MAYBE"}, "s")),
              reply(submit("INVESTIGATE", 0))]
    result, events = run(script)
    steps = {c: (st, d) for c, st, d in request_steps(events)}
    assert steps["u"][0] == "REJECTED" and steps["u"][1].startswith("Unknown tool 'buy_everything'")
    assert steps["i"] == ("REJECTED", "Invalid arguments for get_budget: sku: Field required")
    assert steps["m"][0] == "REJECTED" and steps["m"][1].startswith("Invalid JSON arguments")
    assert steps["l"][0] == "LOCKED" and "locked" in steps["l"][1]
    assert steps["s"][0] == "REJECTED" and steps["s"][1].startswith("Invalid arguments for submit_decision")
    assert [steps[f"b{i}"][0] for i in (1, 2, 3)] == ["ACCEPTED"] * 3
    rejected = {"u", "i", "m", "l", "s"}
    assert not [e for e in events if e.type == "harness_step" and e.data["call_id"] in rejected and e.data["stage"] != "request"]
    assert result.conn.execute("SELECT COUNT(*) FROM purchase_orders WHERE created_by = 'agent'").fetchone()[0] == 0
    assert [(c.name, c.category, c.ok) for c in result.tool_calls] == [
        ("create_po", None, False)] * 3 + [("buy_everything", None, False), ("get_budget", "budget", False)]


def test_tool_messages_are_unchanged_by_the_request_check():
    blocked = [call("create_po", {**S1, "qty": 800}, f"b{i}") for i in (1, 2, 3)]
    script = [reply(*blocked),
              reply(call("get_budget", {"sku": "SKU-1002"}, "v"), call("buy_everything", {}, "u"),
                    call("get_budget", {}, "i"), call("get_budget", '{"sku": ', "m"),
                    call("create_po", {**S1, "qty": 192}, "l")),
              reply(submit("INVESTIGATE", 0))]
    llm = scripted_llm(script)
    run_agent("S1-MODIFY", llm, in_memory=True)
    sent = {m["tool_call_id"]: m["content"] for m in llm.sent[2][-5:]}
    tools = ("get_recommendation, get_product, get_inventory, get_sales_history, get_forecast, get_promotions, "
             "get_purchase_orders, get_suppliers, get_budget, get_storage, get_supplier_events, plan_order, "
             "create_po, modify_po, accept_partial_confirmation, cancel_po, escalate_to_human")
    assert sent == {
        "v": '{"ok": true, "category": "Snacks", "budget_amount": 5000.0, "spent_to_date": 3200.0, '
             '"committed_on_open_pos": 300.0, "remaining": 1500.0}',
        "u": json.dumps({"ok": False, "error": f"Unknown tool 'buy_everything'. Available tools: {tools}"}),
        "i": '{"ok": false, "error": "Invalid arguments for get_budget: sku: Field required"}',
        "m": '{"ok": false, "error": "Invalid JSON arguments: Expecting value: line 1 column 9 (char 8)"}',
        "l": '{"ok": false, "error": "This action has failed 3 times for the same reason. Writes are locked for '
             'this run. Call escalate_to_human, then submit_decision."}',
    }


def test_s2_alt_short_confirmation_is_fixed_after_verifier_feedback():
    script = [
        reply(call("create_po", {**S2, "supplier_id": "SUP-QUICK", "qty": 90})),
        reply(submit("MODIFY", 90)),  # claims what it asked for, not what it got
        reply(call("create_po", {**S2, "supplier_id": "SUP-RAPIDO", "qty": 50, "parent_po_id": "PO-A001"})),
        reply(submit("MODIFY", 90)),
    ]
    llm = scripted_llm(script)
    events = []
    result = run_agent("S2-ALT-ALSO-SHORT", llm, in_memory=True, on_event=events.append)

    first, second = [e.data for e in events if e.type == "verification"]
    assert {"CLAIM_MISMATCH", "UNRESOLVED_SHORTFALL"} <= {f["code"] for f in first["findings"]}
    assert second["passed"] and result.verification.passed and result.outcome == "DECIDED"
    feedback = llm.sent[2][-1]  # the tool result the model saw before its third call
    text = json.loads(feedback["content"])["error"]
    assert feedback["role"] == "tool" and text.startswith("Verification found problems with the final state:")
    assert "CLAIM_MISMATCH" in text and text.endswith("Fix them if you can, then call submit_decision again.")
    quick = results(events, "create_po")[0]
    assert quick["supplier"]["shortfall"] == 50 and quick["shortfall"] == 50
    assert escalations(result) == []


def test_second_failing_submit_flags_the_run_for_a_human():
    script = [reply(call("create_po", {**S2, "supplier_id": "SUP-QUICK", "qty": 90})),
              reply(submit("MODIFY", 90)), reply(submit("MODIFY", 90))]
    result, events = run(script, "S2-ALT-ALSO-SHORT")
    assert result.outcome == "DECIDED" and not result.verification.passed
    assert escalations(result) == ["VERIFICATION_FAILED"]
    assert [e.data["passed"] for e in events if e.type == "verification"] == [False, False]


def test_bad_calls_are_fed_back_and_the_run_continues():
    script = [
        reply(call("get_budget", '{"sku": '), call("buy_everything", {}),
              call("submit_decision", {"decision": "MAYBE"})),
        reply(submit("ACCEPT", 0, 30.0)),
    ]
    result, events = run(script, "S3-ONE-OFF-SPIKE")
    errors = [e.data["result"]["error"] for e in events if e.type == "tool_result" and e.turn == 1 and e.data["by"] == "agent"]
    assert "Invalid JSON arguments" in errors[0] and "Unknown tool 'buy_everything'" in errors[1]
    assert "Invalid arguments for submit_decision" in errors[2] and "decision" in errors[2]
    assert result.outcome == "DECIDED" and result.verification.passed


def test_three_identical_blocked_writes_lock_the_writes():
    blocked = reply(call("create_po", {**S1, "qty": 800}))
    script = [blocked, blocked, blocked,
              reply(call("create_po", {**S1, "qty": 192})),
              reply(call("escalate_to_human", {"kind": "INVESTIGATION", "summary": "Cannot place the PO."})),
              reply(submit("INVESTIGATE", 0))]
    result, events = run(script)
    created = results(events, "create_po")
    assert [r["status"] for r in created[:3]] == ["BLOCKED"] * 3 and "locked" in created[2]["writes_locked"]
    assert "locked" in created[3]["error"]  # the 4th, even with a valid quantity, is refused
    assert results(events, "escalate_to_human")[0]["ok"]
    assert any(e.type == "budget_locked" for e in events)
    assert result.conn.execute("SELECT COUNT(*) FROM purchase_orders WHERE created_by = 'agent'").fetchone()[0] == 0
    assert result.outcome == "DECIDED" and result.verification.passed


def test_a_model_that_never_submits_stops_at_max_steps_and_is_flagged():
    llm = scripted_llm(itertools.repeat(reply(call("get_budget", {"sku": "SKU-1002"}))))
    result = run_agent("S1-MODIFY", llm, in_memory=True)
    assert result.outcome == "MAX_STEPS" and result.steps == 30 and len(llm.sent) == 30
    assert result.decision is None and [f.code for f in result.verification.findings] == ["NO_DECISION"]
    assert escalations(result) == ["VERIFICATION_FAILED"]


NUDGE_TEXT = "Continue by calling a tool. When you are done, call submit_decision."
JSON_NUDGE_TEXT = "Call tools with the tool-calling interface, not as text. When you are done, call submit_decision."
SUBMIT_JSON = ('{"decision": "ACCEPT", "new_units": 0, "daily_demand_used": 30.0, "key_factors": ["f"], '
               '"actions_taken": ["a"], "confidence": "high", "summary": "Done."}')


def nudges(events):
    return [e.data["count"] for e in events if e.type == "nudge"]


def test_every_text_only_reply_gets_a_nudge():
    script = [reply(text="Let me think."), reply(text="Still thinking."), reply(text="Hmm."),
              reply(submit("ACCEPT", 0, 30.0))]
    llm = scripted_llm(script)
    events = []
    result = run_agent("S3-ONE-OFF-SPIKE", llm, in_memory=True, on_event=events.append)
    assert nudges(events) == [1, 2, 3]
    assert llm.sent[1][-1] == {"role": "user", "content": NUDGE_TEXT}
    assert llm.sent[3][-1] == {"role": "user", "content": NUDGE_TEXT}
    assert result.outcome == "DECIDED"


def test_empty_reply_is_stored_with_empty_content_not_null():
    llm = scripted_llm([reply(), reply(submit("ACCEPT", 0, 30.0))])
    run_agent("S3-ONE-OFF-SPIKE", llm, in_memory=True)
    assert llm.sent[1][-2] == {"role": "assistant", "content": ""}


def test_submit_decision_written_as_fenced_json_is_recovered_and_verified():
    result, events = run([reply(text=f'```json\n{{"name": "submit_decision", "arguments": {SUBMIT_JSON}}}\n```')],
                         "S3-ONE-OFF-SPIKE")
    assert result.outcome == "DECIDED" and result.verification.passed and result.decision.decision == "ACCEPT"
    recovered = [e.data for e in events if e.type == "recovered_tool_call"]
    assert recovered[0]["name"] == "submit_decision" and recovered[0]["call_id"] == "recovered-1"
    assert nudges(events) == []
    # the bare decision dict (no name wrapper) is treated as submit_decision arguments too
    llm = scripted_llm([reply(text=f"```json\n{SUBMIT_JSON}\n```")])
    result = run_agent("S3-ONE-OFF-SPIKE", llm, in_memory=True)
    assert result.outcome == "DECIDED" and result.verification.passed


def test_recovered_call_keeps_the_message_sequence_valid():
    text = '{"name": "get_promotions", "arguments": {"sku": "SKU-1002"}}'
    llm = scripted_llm([reply(text=text), reply(submit("ACCEPT", 0, 30.0))])
    events = []
    result = run_agent("S1-MODIFY", llm, in_memory=True, on_event=events.append)
    assistant, tool = llm.sent[1][-2:]
    assert assistant["content"] == text
    assert assistant["tool_calls"] == [{"id": "recovered-1", "type": "function", "function": {
        "name": "get_promotions", "arguments": '{"sku": "SKU-1002"}'}}]
    assert tool["role"] == "tool" and tool["tool_call_id"] == "recovered-1"
    assert [r["ok"] for r in results(events, "get_promotions")] == [True]
    assert result.outcome == "DECIDED"


def test_unrecoverable_json_is_nudged_not_executed():
    two = f"```json\n{SUBMIT_JSON}\n```\nor\n```json\n{SUBMIT_JSON}\n```"
    unknown = '{"name": "buy_everything", "arguments": {}}'
    llm = scripted_llm([reply(text=two), reply(text=unknown), reply(text="just prose"),
                        reply(submit("ACCEPT", 0, 30.0))])
    events = []
    result = run_agent("S3-ONE-OFF-SPIKE", llm, in_memory=True, on_event=events.append)
    assert not [e for e in events if e.type == "recovered_tool_call"]
    assert nudges(events) == [1, 2, 3]
    assert [llm.sent[i][-1]["content"] for i in (1, 2, 3)] == [JSON_NUDGE_TEXT, JSON_NUDGE_TEXT, NUDGE_TEXT]
    assert result.outcome == "DECIDED"


def stale_submit_script(*ending):
    """A rejected first submit, a fix, then whatever `ending` does (the run never submits again)."""
    return [reply(call("create_po", {**S2, "supplier_id": "SUP-QUICK", "qty": 90})),
            reply(submit("MODIFY", 90)),
            reply(call("create_po", {**S2, "supplier_id": "SUP-RAPIDO", "qty": 50, "parent_po_id": "PO-A001"})),
            *ending]


def assert_stale_decision_is_dropped(result, events, outcome):
    assert result.outcome == outcome and result.decision is None
    assert [f.code for f in result.verification.findings] == ["NO_DECISION"]
    assert escalations(result) == ["VERIFICATION_FAILED"]
    assert [e.data["passed"] for e in events if e.type == "verification"][-1] is False
    assert [e.type for e in events if e.type == "flagged"] == ["flagged"]


def test_max_steps_after_a_rejected_submit_does_not_reuse_the_stale_decision():
    budget = reply(call("get_budget", {"sku": "SKU-2003"}))
    result, events = run(stale_submit_script(*[budget] * 3), "S2-ALT-ALSO-SHORT", max_turns=6)
    assert_stale_decision_is_dropped(result, events, "MAX_STEPS")


def test_llm_error_after_a_rejected_submit_does_not_reuse_the_stale_decision():
    result, events = run(stale_submit_script(TimeoutError("down")), "S2-ALT-ALSO-SHORT")
    assert_stale_decision_is_dropped(result, events, "LLM_ERROR")


def test_flagged_event_carries_the_escalation_and_findings():
    result, events = run([reply(call("get_budget", {"sku": "SKU-1002"}))] * 2, "S1-MODIFY", max_turns=2)
    flagged = [e.data for e in events if e.type == "flagged"]
    assert len(flagged) == 1 and flagged[0]["findings"] == [f"NO_DECISION: {result.verification.findings[0].message}"]
    assert flagged[0]["escalation_id"] and not [e for e in events if e.type == "tool_result" and e.data["name"] == "flag_run"]


def test_a_second_submit_in_the_same_turn_is_ignored_and_not_a_verifier_round():
    script = [reply(call("create_po", {**S2, "supplier_id": "SUP-QUICK", "qty": 90})),
              reply(submit("MODIFY", 90), submit("MODIFY", 90)),
              reply(call("create_po", {**S2, "supplier_id": "SUP-RAPIDO", "qty": 50, "parent_po_id": "PO-A001"})),
              reply(submit("MODIFY", 90))]
    result, events = run(script, "S2-ALT-ALSO-SHORT")
    second = [e.data["result"] for e in events if e.type == "tool_result" and e.turn == 2][1]
    assert second["error"] == "Ignored: only one submit_decision per turn."
    assert [e.data["passed"] for e in events if e.type == "verification"] == [False, True]
    assert result.outcome == "DECIDED" and result.verification.passed and escalations(result) == []


def truncation_run(*token_counts):
    script = [reply(call("create_po", {**S1, "qty": 192}), tokens_in=n) for n in token_counts]
    return run(script)


def test_exact_context_window_size_stops_the_run_before_any_tool_runs():
    result, events = truncation_run(4096)
    assert result.outcome == "CONTEXT_TRUNCATED" and result.steps == 1 and result.decision is None
    assert not [e for e in events if e.type == "tool_call" and e.data["by"] == "agent"]
    assert result.conn.execute("SELECT COUNT(*) FROM purchase_orders WHERE created_by = 'agent'").fetchone()[0] == 0
    message = next(e.data["message"] for e in events if e.type == "error")
    assert message == ("the model server cut the prompt to 4096 tokens; "
                       "raise its context window (see ollama/Modelfile.*)")
    assert escalations(result) == ["VERIFICATION_FAILED"] and events[-1].data["outcome"] == "CONTEXT_TRUNCATED"


def test_shrinking_input_tokens_stop_the_run_on_that_turn():
    result, events = truncation_run(4174, 2411)
    assert result.outcome == "CONTEXT_TRUNCATED" and result.steps == 2
    assert len([e for e in events if e.type == "tool_call" and e.data["by"] == "agent"]) == 1
    assert "cut the prompt to 2411 tokens" in next(e.data["message"] for e in events if e.type == "error")


def test_growing_or_missing_usage_does_not_trip_the_guard():
    script = [reply(call("get_budget", {"sku": "SKU-1002"}), tokens_in=3000),
              reply(call("get_budget", {"sku": "SKU-1002"}), tokens_in=None),
              reply(call("get_budget", {"sku": "SKU-1002"}), tokens_in=3500),
              reply(submit("ACCEPT", 0), tokens_in=3500)]
    result, _ = run(script, "S3-ONE-OFF-SPIKE")
    assert result.outcome == "DECIDED"


def test_llm_exception_ends_the_run_without_raising():
    result, events = run([reply(call("get_budget", {"sku": "SKU-1002"})), TimeoutError("provider timed out")])
    assert result.outcome == "LLM_ERROR" and result.decision is None
    assert [e.data["message"] for e in events if e.type == "error"] == ["TimeoutError: provider timed out"]
    assert events[-1].type == "run_finished" and events[-1].data["outcome"] == "LLM_ERROR"
    assert escalations(result) == ["VERIFICATION_FAILED"]
