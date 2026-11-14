# Evaluation: do_nothing

Agent version: git b0fe06c, prompt 2cf70775b782.

Every score is a deterministic check on the final database and the tool calls, with its reason written next to it.
11 runs: 11 scenarios x 1 repeat(s).

## Headline

- Scenarios passed (every repeat passed): **0/11**
- Runs passed: **0/11 (0%)**
- Run outcomes: DECIDED x11

| Check | Passed |
|---|---|
| decision | 1/11 (9%) |
| information | 0/11 (0%) |
| constraints | 11/11 (100%) |
| action | 3/11 (27%) |
| validation | 4/11 (36%) |
| recovery | n/a |

## Scenarios

A check shows ✓ when every repeat passed, ✗ when none did, k/n when mixed, and - when it did not apply.
Consistency is how many runs gave the most common decision.
Repeat reads counts, per run, the reads that repeated an earlier successful read with the same arguments.

| Scenario | Expected | Got | New units (band) | decision | information | constraints | action | validation | recovery | Consistency | Repeat reads |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1-MODIFY | MODIFY | REJECT | 0 (168-240) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | 0 |
| S1-ACCEPT | ACCEPT | REJECT | 0 (456-504) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | 0 |
| S1-REJECT | REJECT | REJECT | 0 (0-0) | ✓ | ✗ | ✓ | ✓ | ✓ | - | 1/1 | 0 |
| S1-INVESTIGATE | INVESTIGATE | REJECT | 0 (0-0) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | 0 |
| S2-SOURCE-ELSEWHERE | MODIFY | REJECT | 0 (90-220) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | 0 |
| S2-ACCEPT-SHORT | ACCEPT | REJECT | 0 (0-0) | ✗ | ✗ | ✓ | ✓ | ✓ | - | 1/1 | 0 |
| S2-ALT-ALSO-SHORT | MODIFY | REJECT | 0 (90-220) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | 0 |
| S3-SUSTAINED-SPIKE | MODIFY | REJECT | 0 (180-650) | ✗ | ✗ | ✓ | ✗ | ✓ | - | 1/1 | 0 |
| S3-PROMO-ENDING | ACCEPT | REJECT | 0 (0-0) | ✗ | ✗ | ✓ | ✓ | ✓ | - | 1/1 | 0 |
| S4-BUDGET | MODIFY | REJECT | 0 (120-396) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | 0 |
| S4-MOQ-VS-SHELF-LIFE | MODIFY | REJECT | 0 (36-72) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | 0 |

## Why it failed

- S1-MODIFY, run 20261114T130547-05461b, decision: decided REJECT, expected MODIFY
- S1-MODIFY, run 20261114T130547-05461b, information: never read: budget, forecast, inventory, open_pos, storage, suppliers
- S1-MODIFY, run 20261114T130547-05461b, action: 0 units, expected 168-240
- S1-MODIFY, run 20261114T130547-05461b, validation: verifier findings: STOCKOUT_UNRESOLVED
- S1-ACCEPT, run 20261114T130547-c224ae, decision: decided REJECT, expected ACCEPT
- S1-ACCEPT, run 20261114T130547-c224ae, information: never read: budget, forecast, inventory, open_pos, storage, suppliers
- S1-ACCEPT, run 20261114T130547-c224ae, action: 0 units, expected 456-504
- S1-ACCEPT, run 20261114T130547-c224ae, validation: verifier findings: STOCKOUT_UNRESOLVED
- S1-REJECT, run 20261114T130547-f6c6cb, information: never read: forecast, inventory, open_pos
- S1-INVESTIGATE, run 20261114T130547-03a03e, decision: decided REJECT, expected INVESTIGATE
- S1-INVESTIGATE, run 20261114T130547-03a03e, information: never read: inventory, open_pos, sales_history
- S1-INVESTIGATE, run 20261114T130547-03a03e, action: no INVESTIGATION escalation was raised
- S1-INVESTIGATE, run 20261114T130547-03a03e, validation: verifier findings: STOCKOUT_UNRESOLVED
- S2-SOURCE-ELSEWHERE, run 20261114T130547-3b1c2c, decision: decided REJECT, expected MODIFY
- S2-SOURCE-ELSEWHERE, run 20261114T130547-3b1c2c, information: never read: budget, forecast, inventory, open_pos, supplier_events, suppliers
- S2-SOURCE-ELSEWHERE, run 20261114T130547-3b1c2c, action: 0 units, expected 90-220
- S2-SOURCE-ELSEWHERE, run 20261114T130547-3b1c2c, validation: verifier findings: STOCKOUT_UNRESOLVED
- S2-ACCEPT-SHORT, run 20261114T130547-128603, decision: decided REJECT, expected ACCEPT
- S2-ACCEPT-SHORT, run 20261114T130547-128603, information: never read: forecast, inventory, open_pos, supplier_events
- S2-ALT-ALSO-SHORT, run 20261114T130547-dba3b9, decision: decided REJECT, expected MODIFY
- S2-ALT-ALSO-SHORT, run 20261114T130547-dba3b9, information: never read: budget, forecast, inventory, open_pos, supplier_events, suppliers
- S2-ALT-ALSO-SHORT, run 20261114T130547-dba3b9, action: 0 units, expected 90-220
- S2-ALT-ALSO-SHORT, run 20261114T130547-dba3b9, validation: verifier findings: STOCKOUT_UNRESOLVED
- S3-SUSTAINED-SPIKE, run 20261114T130547-304d8a, decision: decided REJECT, expected MODIFY
- S3-SUSTAINED-SPIKE, run 20261114T130547-304d8a, information: never read: forecast, inventory, open_pos, promotions, sales_history, suppliers
- S3-SUSTAINED-SPIKE, run 20261114T130547-304d8a, action: 0 units, expected 180-650
- S3-PROMO-ENDING, run 20261114T130547-b46ee3, decision: decided REJECT, expected ACCEPT
- S3-PROMO-ENDING, run 20261114T130547-b46ee3, information: never read: forecast, inventory, open_pos, promotions, sales_history
- S4-BUDGET, run 20261114T130547-d8b015, decision: decided REJECT, expected MODIFY
- S4-BUDGET, run 20261114T130547-d8b015, information: never read: budget, forecast, inventory, open_pos, suppliers
- S4-BUDGET, run 20261114T130547-d8b015, action: 0 units, expected 120-396; no BUDGET_INCREASE escalation was raised
- S4-BUDGET, run 20261114T130547-d8b015, validation: verifier findings: STOCKOUT_UNRESOLVED
- S4-MOQ-VS-SHELF-LIFE, run 20261114T130547-c68aa9, decision: decided REJECT, expected MODIFY
- S4-MOQ-VS-SHELF-LIFE, run 20261114T130547-c68aa9, information: never read: forecast, inventory, suppliers
- S4-MOQ-VS-SHELF-LIFE, run 20261114T130547-c68aa9, action: 0 units, expected 36-72
- S4-MOQ-VS-SHELF-LIFE, run 20261114T130547-c68aa9, validation: verifier findings: STOCKOUT_UNRESOLVED

## Cost and speed

- Mean turns per run: 1.6
- Mean tool calls chosen by the agent: 0.0
- Mean blocked or unjustified writes: 0.00
- Mean tokens per run: 0 in, 0 out
- Mean latency per run: 0.0s (total 0s)
