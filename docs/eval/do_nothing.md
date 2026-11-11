# Evaluation: do_nothing

Every score is a deterministic check on the final database and the tool calls, with its reason written next to it.
12 runs: 12 scenarios x 1 repeat(s).

## Headline

- Scenarios passed (every repeat passed): **1/12**
- Runs passed: **1/12 (8%)**
- Run outcomes: DECIDED x12

| Check | Passed |
|---|---|
| decision | 1/12 (8%) |
| information | 4/12 (33%) |
| constraints | 12/12 (100%) |
| action | 4/12 (33%) |
| validation | 5/12 (42%) |
| recovery | n/a |

## Scenarios

A check shows ✓ when every repeat passed, ✗ when none did, k/n when mixed, and - when it did not apply.
Consistency is how many runs gave the most common decision.
Read by agent lists the information categories the model fetched itself (any repeat), beyond the preload.

| Scenario | Expected | Got | New units (band) | decision | information | constraints | action | validation | recovery | Consistency | Read by agent |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1-MODIFY | MODIFY | REJECT | 0 (168-240) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | none |
| S1-ACCEPT | ACCEPT | REJECT | 0 (456-504) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | none |
| S1-REJECT | REJECT | REJECT | 0 (0-0) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 1/1 | none |
| S1-INVESTIGATE | INVESTIGATE | REJECT | 0 (0-0) | ✗ | ✓ | ✓ | ✗ | ✗ | - | 1/1 | none |
| S2-SOURCE-ELSEWHERE | MODIFY | REJECT | 0 (90-220) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | none |
| S2-ACCEPT-SHORT | ACCEPT | REJECT | 0 (0-0) | ✗ | ✓ | ✓ | ✓ | ✓ | - | 1/1 | none |
| S2-ALT-ALSO-SHORT | MODIFY | REJECT | 0 (90-220) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | none |
| S3-SUSTAINED-SPIKE | MODIFY | REJECT | 0 (180-650) | ✗ | ✗ | ✓ | ✗ | ✓ | - | 1/1 | none |
| S3-ONE-OFF-SPIKE | ACCEPT | REJECT | 0 (0-0) | ✗ | ✓ | ✓ | ✓ | ✓ | - | 1/1 | none |
| S3-PROMO-ENDING | ACCEPT | REJECT | 0 (0-0) | ✗ | ✗ | ✓ | ✓ | ✓ | - | 1/1 | none |
| S4-BUDGET | MODIFY | REJECT | 0 (120-396) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | none |
| S4-MOQ-VS-SHELF-LIFE | MODIFY | REJECT | 0 (36-72) | ✗ | ✗ | ✓ | ✗ | ✗ | - | 1/1 | none |

## Why it failed

- S1-MODIFY, run 20261111T184648-93b66c, decision: decided REJECT, expected MODIFY
- S1-MODIFY, run 20261111T184648-93b66c, information: never read: budget, storage, suppliers
- S1-MODIFY, run 20261111T184648-93b66c, action: 0 units, expected 168-240
- S1-MODIFY, run 20261111T184648-93b66c, validation: verifier findings: STOCKOUT_UNRESOLVED
- S1-ACCEPT, run 20261111T184648-ccd732, decision: decided REJECT, expected ACCEPT
- S1-ACCEPT, run 20261111T184648-ccd732, information: never read: budget, storage, suppliers
- S1-ACCEPT, run 20261111T184648-ccd732, action: 0 units, expected 456-504
- S1-ACCEPT, run 20261111T184648-ccd732, validation: verifier findings: STOCKOUT_UNRESOLVED
- S1-INVESTIGATE, run 20261111T184648-09b721, decision: decided REJECT, expected INVESTIGATE
- S1-INVESTIGATE, run 20261111T184648-09b721, action: no INVESTIGATION escalation was raised
- S1-INVESTIGATE, run 20261111T184648-09b721, validation: verifier findings: STOCKOUT_UNRESOLVED
- S2-SOURCE-ELSEWHERE, run 20261111T184648-8e0f76, decision: decided REJECT, expected MODIFY
- S2-SOURCE-ELSEWHERE, run 20261111T184648-8e0f76, information: never read: budget, suppliers
- S2-SOURCE-ELSEWHERE, run 20261111T184648-8e0f76, action: 0 units, expected 90-220
- S2-SOURCE-ELSEWHERE, run 20261111T184648-8e0f76, validation: verifier findings: STOCKOUT_UNRESOLVED
- S2-ACCEPT-SHORT, run 20261111T184648-daebdd, decision: decided REJECT, expected ACCEPT
- S2-ALT-ALSO-SHORT, run 20261111T184648-b2a25d, decision: decided REJECT, expected MODIFY
- S2-ALT-ALSO-SHORT, run 20261111T184648-b2a25d, information: never read: budget, suppliers
- S2-ALT-ALSO-SHORT, run 20261111T184648-b2a25d, action: 0 units, expected 90-220
- S2-ALT-ALSO-SHORT, run 20261111T184648-b2a25d, validation: verifier findings: STOCKOUT_UNRESOLVED
- S3-SUSTAINED-SPIKE, run 20261111T184648-51e649, decision: decided REJECT, expected MODIFY
- S3-SUSTAINED-SPIKE, run 20261111T184648-51e649, information: never read: promotions, suppliers
- S3-SUSTAINED-SPIKE, run 20261111T184648-51e649, action: 0 units, expected 180-650
- S3-ONE-OFF-SPIKE, run 20261111T184648-98a261, decision: decided REJECT, expected ACCEPT
- S3-PROMO-ENDING, run 20261111T184648-b76e68, decision: decided REJECT, expected ACCEPT
- S3-PROMO-ENDING, run 20261111T184648-b76e68, information: never read: promotions
- S4-BUDGET, run 20261111T184648-6b5669, decision: decided REJECT, expected MODIFY
- S4-BUDGET, run 20261111T184648-6b5669, information: never read: budget, suppliers
- S4-BUDGET, run 20261111T184648-6b5669, action: 0 units, expected 120-396; no BUDGET_INCREASE escalation was raised
- S4-BUDGET, run 20261111T184648-6b5669, validation: verifier findings: STOCKOUT_UNRESOLVED
- S4-MOQ-VS-SHELF-LIFE, run 20261111T184648-c64a94, decision: decided REJECT, expected MODIFY
- S4-MOQ-VS-SHELF-LIFE, run 20261111T184648-c64a94, information: never read: suppliers
- S4-MOQ-VS-SHELF-LIFE, run 20261111T184648-c64a94, action: 0 units, expected 36-72
- S4-MOQ-VS-SHELF-LIFE, run 20261111T184648-c64a94, validation: verifier findings: STOCKOUT_UNRESOLVED

## Cost and speed

- Mean turns per run: 1.6
- Mean tool calls chosen by the agent: 0.0
- Mean blocked or unjustified writes: 0.00
- Mean tokens per run: 0 in, 0 out
- Mean latency per run: 0.0s (total 0s)
