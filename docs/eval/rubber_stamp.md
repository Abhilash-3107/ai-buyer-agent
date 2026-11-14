# Evaluation: rubber_stamp

Agent version: git b0fe06c, prompt 2cf70775b782.

Every score is a deterministic check on the final database and the tool calls, with its reason written next to it.
11 runs: 11 scenarios x 1 repeat(s).

## Headline

- Scenarios passed (every repeat passed): **0/11**
- Runs passed: **0/11 (0%)**
- Run outcomes: DECIDED x11

| Check | Passed |
|---|---|
| decision | 3/11 (27%) |
| information | 0/11 (0%) |
| constraints | 11/11 (100%) |
| action | 3/11 (27%) |
| validation | 5/11 (45%) |
| recovery | 0/4 (0%) |

## Scenarios

A check shows ✓ when every repeat passed, ✗ when none did, k/n when mixed, and - when it did not apply.
Consistency is how many runs gave the most common decision.
Repeat reads counts, per run, the reads that repeated an earlier successful read with the same arguments.

| Scenario | Expected | Got | New units (band) | decision | information | constraints | action | validation | recovery | Consistency | Repeat reads |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1-MODIFY | MODIFY | ACCEPT | 0 (168-240) | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | 1/1 | 0 |
| S1-ACCEPT | ACCEPT | ACCEPT | 480 (456-504) | ✓ | ✗ | ✓ | ✓ | ✓ | - | 1/1 | 0 |
| S1-REJECT | REJECT | ACCEPT | 480 (0-0) | ✗ | ✗ | ✓ | ✗ | ✓ | - | 1/1 | 0 |
| S1-INVESTIGATE | INVESTIGATE | ACCEPT | 0 (0-0) | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | 1/1 | 0 |
| S2-SOURCE-ELSEWHERE | MODIFY | ACCEPT | 0 (90-220) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | 0 |
| S2-ACCEPT-SHORT | ACCEPT | ACCEPT | 0 (0-0) | ✓ | ✗ | ✓ | ✓ | ✓ | - | 1/1 | 0 |
| S2-ALT-ALSO-SHORT | MODIFY | ACCEPT | 0 (90-220) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | 0 |
| S3-SUSTAINED-SPIKE | MODIFY | ACCEPT | 420 (180-650) | ✗ | ✗ | ✓ | ✓ | ✓ | - | 1/1 | 0 |
| S3-PROMO-ENDING | ACCEPT | ACCEPT | 480 (0-0) | ✓ | ✗ | ✓ | ✗ | ✓ | - | 1/1 | 0 |
| S4-BUDGET | MODIFY | ACCEPT | 0 (120-396) | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | 1/1 | 0 |
| S4-MOQ-VS-SHELF-LIFE | MODIFY | ACCEPT | 0 (36-72) | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | 1/1 | 0 |

## Why it failed

- S1-MODIFY, run 20261114T130547-fc0140, decision: decided ACCEPT, expected MODIFY
- S1-MODIFY, run 20261114T130547-fc0140, information: never read: budget, forecast, inventory, open_pos, storage, suppliers
- S1-MODIFY, run 20261114T130547-fc0140, action: 0 units, expected 168-240
- S1-MODIFY, run 20261114T130547-fc0140, validation: verifier findings: STOCKOUT_UNRESOLVED
- S1-MODIFY, run 20261114T130547-fc0140, recovery: 1 of 1 failed writes (create_po BLOCKED) were never followed by a successful write or an escalation
- S1-ACCEPT, run 20261114T130547-edec76, information: never read: budget, forecast, inventory, open_pos, storage, suppliers
- S1-REJECT, run 20261114T130547-d6d48a, decision: decided ACCEPT, expected REJECT
- S1-REJECT, run 20261114T130547-d6d48a, information: never read: forecast, inventory, open_pos
- S1-REJECT, run 20261114T130547-d6d48a, action: 480 units, expected 0
- S1-INVESTIGATE, run 20261114T130547-2837e4, decision: decided ACCEPT, expected INVESTIGATE
- S1-INVESTIGATE, run 20261114T130547-2837e4, information: never read: inventory, open_pos
- S1-INVESTIGATE, run 20261114T130547-2837e4, action: no INVESTIGATION escalation was raised
- S1-INVESTIGATE, run 20261114T130547-2837e4, validation: verifier findings: STOCKOUT_UNRESOLVED
- S1-INVESTIGATE, run 20261114T130547-2837e4, recovery: 1 of 1 failed writes (create_po BLOCKED) were never followed by a successful write or an escalation
- S2-SOURCE-ELSEWHERE, run 20261114T130547-517603, decision: decided ACCEPT, expected MODIFY
- S2-SOURCE-ELSEWHERE, run 20261114T130547-517603, information: never read: budget, forecast, inventory, open_pos, supplier_events, suppliers
- S2-SOURCE-ELSEWHERE, run 20261114T130547-517603, action: 0 units, expected 90-220
- S2-SOURCE-ELSEWHERE, run 20261114T130547-517603, validation: verifier findings: STOCKOUT_UNRESOLVED
- S2-ACCEPT-SHORT, run 20261114T130547-d6f321, information: never read: forecast, inventory, open_pos, supplier_events
- S2-ALT-ALSO-SHORT, run 20261114T130547-dbdf17, decision: decided ACCEPT, expected MODIFY
- S2-ALT-ALSO-SHORT, run 20261114T130547-dbdf17, information: never read: budget, forecast, inventory, open_pos, supplier_events, suppliers
- S2-ALT-ALSO-SHORT, run 20261114T130547-dbdf17, action: 0 units, expected 90-220
- S2-ALT-ALSO-SHORT, run 20261114T130547-dbdf17, validation: verifier findings: STOCKOUT_UNRESOLVED
- S3-SUSTAINED-SPIKE, run 20261114T130547-786d95, decision: decided ACCEPT, expected MODIFY
- S3-SUSTAINED-SPIKE, run 20261114T130547-786d95, information: never read: forecast, inventory, open_pos, promotions
- S3-PROMO-ENDING, run 20261114T130547-2afcc2, information: never read: forecast, inventory, open_pos, promotions
- S3-PROMO-ENDING, run 20261114T130547-2afcc2, action: 480 units, expected 0
- S4-BUDGET, run 20261114T130547-d57366, decision: decided ACCEPT, expected MODIFY
- S4-BUDGET, run 20261114T130547-d57366, information: never read: budget, forecast, inventory, open_pos, suppliers
- S4-BUDGET, run 20261114T130547-d57366, action: 0 units, expected 120-396; no BUDGET_INCREASE escalation was raised
- S4-BUDGET, run 20261114T130547-d57366, validation: verifier findings: STOCKOUT_UNRESOLVED
- S4-BUDGET, run 20261114T130547-d57366, recovery: 1 of 1 failed writes (create_po BLOCKED) were never followed by a successful write or an escalation
- S4-MOQ-VS-SHELF-LIFE, run 20261114T130547-642a47, decision: decided ACCEPT, expected MODIFY
- S4-MOQ-VS-SHELF-LIFE, run 20261114T130547-642a47, information: never read: forecast, inventory, suppliers
- S4-MOQ-VS-SHELF-LIFE, run 20261114T130547-642a47, action: 0 units, expected 36-72
- S4-MOQ-VS-SHELF-LIFE, run 20261114T130547-642a47, validation: verifier findings: STOCKOUT_UNRESOLVED
- S4-MOQ-VS-SHELF-LIFE, run 20261114T130547-642a47, recovery: 1 of 1 failed writes (create_po BLOCKED) were never followed by a successful write or an escalation

## Cost and speed

- Mean turns per run: 4.2
- Mean tool calls chosen by the agent: 2.6
- Mean blocked or unjustified writes: 0.36
- Mean tokens per run: 0 in, 0 out
- Mean latency per run: 0.0s (total 0s)
