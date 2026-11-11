# Evaluation: rubber_stamp

Every score is a deterministic check on the final database and the tool calls, with its reason written next to it.
12 runs: 12 scenarios x 1 repeat(s).

## Headline

- Scenarios passed (every repeat passed): **1/12**
- Runs passed: **1/12 (8%)**
- Run outcomes: DECIDED x12

| Check | Passed |
|---|---|
| decision | 4/12 (33%) |
| information | 4/12 (33%) |
| constraints | 12/12 (100%) |
| action | 4/12 (33%) |
| validation | 6/12 (50%) |
| recovery | 1/5 (20%) |

## Scenarios

A check shows ✓ when every repeat passed, ✗ when none did, k/n when mixed, and - when it did not apply.
Consistency is how many runs gave the most common decision.
Read by agent lists the information categories the model fetched itself (any repeat), beyond the preload.

| Scenario | Expected | Got | New units (band) | decision | information | constraints | action | validation | recovery | Consistency | Read by agent |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1-MODIFY | MODIFY | ACCEPT | 0 (168-240) | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | 1/1 | none |
| S1-ACCEPT | ACCEPT | ACCEPT | 480 (456-504) | ✓ | ✗ | ✓ | ✓ | ✓ | - | 1/1 | none |
| S1-REJECT | REJECT | ACCEPT | 0 (0-0) | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | 1/1 | none |
| S1-INVESTIGATE | INVESTIGATE | ACCEPT | 0 (0-0) | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | 1/1 | none |
| S2-SOURCE-ELSEWHERE | MODIFY | ACCEPT | 0 (90-220) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | none |
| S2-ACCEPT-SHORT | ACCEPT | ACCEPT | 0 (0-0) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 1/1 | none |
| S2-ALT-ALSO-SHORT | MODIFY | ACCEPT | 0 (90-220) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | none |
| S3-SUSTAINED-SPIKE | MODIFY | ACCEPT | 420 (180-650) | ✗ | ✗ | ✓ | ✓ | ✓ | - | 1/1 | suppliers |
| S3-ONE-OFF-SPIKE | ACCEPT | ACCEPT | 336 (0-0) | ✓ | ✓ | ✓ | ✗ | ✓ | - | 1/1 | suppliers |
| S3-PROMO-ENDING | ACCEPT | ACCEPT | 480 (0-0) | ✓ | ✗ | ✓ | ✗ | ✓ | - | 1/1 | suppliers |
| S4-BUDGET | MODIFY | ACCEPT | 0 (120-396) | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | 1/1 | none |
| S4-MOQ-VS-SHELF-LIFE | MODIFY | ACCEPT | 0 (36-72) | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | 1/1 | none |

## Why it failed

- S1-MODIFY, run 20261111T184648-a93150, decision: decided ACCEPT, expected MODIFY
- S1-MODIFY, run 20261111T184648-a93150, information: never read: budget, storage, suppliers
- S1-MODIFY, run 20261111T184648-a93150, action: 0 units, expected 168-240
- S1-MODIFY, run 20261111T184648-a93150, validation: verifier findings: STOCKOUT_UNRESOLVED
- S1-MODIFY, run 20261111T184648-a93150, recovery: 1 of 1 failed writes (create_po BLOCKED) were never followed by a successful write or an escalation
- S1-ACCEPT, run 20261111T184648-6b40ea, information: never read: budget, storage, suppliers
- S1-REJECT, run 20261111T184648-393f21, decision: decided ACCEPT, expected REJECT
- S1-INVESTIGATE, run 20261111T184648-a3ecf1, decision: decided ACCEPT, expected INVESTIGATE
- S1-INVESTIGATE, run 20261111T184648-a3ecf1, action: no INVESTIGATION escalation was raised
- S1-INVESTIGATE, run 20261111T184648-a3ecf1, validation: verifier findings: STOCKOUT_UNRESOLVED
- S1-INVESTIGATE, run 20261111T184648-a3ecf1, recovery: 1 of 1 failed writes (create_po BLOCKED) were never followed by a successful write or an escalation
- S2-SOURCE-ELSEWHERE, run 20261111T184648-aa200b, decision: decided ACCEPT, expected MODIFY
- S2-SOURCE-ELSEWHERE, run 20261111T184648-aa200b, information: never read: budget, suppliers
- S2-SOURCE-ELSEWHERE, run 20261111T184648-aa200b, action: 0 units, expected 90-220
- S2-SOURCE-ELSEWHERE, run 20261111T184648-aa200b, validation: verifier findings: STOCKOUT_UNRESOLVED
- S2-ALT-ALSO-SHORT, run 20261111T184648-1369c5, decision: decided ACCEPT, expected MODIFY
- S2-ALT-ALSO-SHORT, run 20261111T184648-1369c5, information: never read: budget, suppliers
- S2-ALT-ALSO-SHORT, run 20261111T184648-1369c5, action: 0 units, expected 90-220
- S2-ALT-ALSO-SHORT, run 20261111T184648-1369c5, validation: verifier findings: STOCKOUT_UNRESOLVED
- S3-SUSTAINED-SPIKE, run 20261111T184648-825718, decision: decided ACCEPT, expected MODIFY
- S3-SUSTAINED-SPIKE, run 20261111T184648-825718, information: never read: promotions
- S3-ONE-OFF-SPIKE, run 20261111T184648-8bff38, action: 336 units, expected 0
- S3-PROMO-ENDING, run 20261111T184648-739fc8, information: never read: promotions
- S3-PROMO-ENDING, run 20261111T184648-739fc8, action: 480 units, expected 0
- S4-BUDGET, run 20261111T184648-2c70c6, decision: decided ACCEPT, expected MODIFY
- S4-BUDGET, run 20261111T184648-2c70c6, information: never read: budget, suppliers
- S4-BUDGET, run 20261111T184648-2c70c6, action: 0 units, expected 120-396; no BUDGET_INCREASE escalation was raised
- S4-BUDGET, run 20261111T184648-2c70c6, validation: verifier findings: STOCKOUT_UNRESOLVED
- S4-BUDGET, run 20261111T184648-2c70c6, recovery: 1 of 1 failed writes (create_po BLOCKED) were never followed by a successful write or an escalation
- S4-MOQ-VS-SHELF-LIFE, run 20261111T184648-854333, decision: decided ACCEPT, expected MODIFY
- S4-MOQ-VS-SHELF-LIFE, run 20261111T184648-854333, information: never read: suppliers
- S4-MOQ-VS-SHELF-LIFE, run 20261111T184648-854333, action: 0 units, expected 36-72
- S4-MOQ-VS-SHELF-LIFE, run 20261111T184648-854333, validation: verifier findings: STOCKOUT_UNRESOLVED
- S4-MOQ-VS-SHELF-LIFE, run 20261111T184648-854333, recovery: 1 of 1 failed writes (create_po BLOCKED) were never followed by a successful write or an escalation

## Cost and speed

- Mean turns per run: 3.0
- Mean tool calls chosen by the agent: 1.5
- Mean blocked or unjustified writes: 0.42
- Mean tokens per run: 0 in, 0 out
- Mean latency per run: 0.0s (total 0s)
