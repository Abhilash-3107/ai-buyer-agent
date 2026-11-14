# Evaluation: gpt-6-luna

Agent version: git b0fe06c, prompt 2cf70775b782.

Every score is a deterministic check on the final database and the tool calls, with its reason written next to it.
33 runs: 11 scenarios x 3 repeat(s).

## Headline

- Scenarios passed (every repeat passed): **9/11**
- Runs passed: **29/33 (88%)**
- Run outcomes: DECIDED x33

| Check | Passed |
|---|---|
| decision | 30/33 (91%) |
| information | 33/33 (100%) |
| constraints | 33/33 (100%) |
| action | 31/33 (94%) |
| validation | 32/33 (97%) |
| recovery | 6/6 (100%) |

## Scenarios

A check shows ✓ when every repeat passed, ✗ when none did, k/n when mixed, and - when it did not apply.
Consistency is how many runs gave the most common decision.
Repeat reads counts, per run, the reads that repeated an earlier successful read with the same arguments.

| Scenario | Expected | Got | New units (band) | decision | information | constraints | action | validation | recovery | Consistency | Repeat reads |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1-MODIFY | MODIFY | MODIFY | 192, 192, 192 (168-240) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 3/3 | 0, 0, 0 |
| S1-ACCEPT | ACCEPT | ACCEPT | 480, 480, 480 (456-504) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 3/3 | 0, 0, 0 |
| S1-REJECT | REJECT | REJECT | 0, 0, 0 (0-0) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 3/3 | 0, 0, 0 |
| S1-INVESTIGATE | INVESTIGATE | INVESTIGATE | 0, 0, 0 (0-0) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 3/3 | 0, 0, 0 |
| S2-SOURCE-ELSEWHERE | MODIFY | MODIFY | 90, 90, 90 (90-220) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 3/3 | 0, 0, 0 |
| S2-ACCEPT-SHORT | ACCEPT | ACCEPT | 0, 0, 0 (0-0) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 3/3 | 0, 0, 0 |
| S2-ALT-ALSO-SHORT | MODIFY | MODIFY | 130, 130, 130 (90-220) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 3/3 | 1, 0, 1 |
| S3-SUSTAINED-SPIKE | MODIFY | MODIFY | 192, 192, 192 (180-650) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 3/3 | 1, 1, 1 |
| S3-PROMO-ENDING | ACCEPT | MODIFY | 480, 480, 0 (0-0) | ✗ | ✓ | ✓ | 1/3 | ✓ | - | 2/3 | 1, 0, 0 |
| S4-BUDGET | MODIFY | MODIFY | 120, 396, 396 (120-396) | ✓ | ✓ | ✓ | ✓ | 2/3 | - | 3/3 | 0, 0, 0 |
| S4-MOQ-VS-SHELF-LIFE | MODIFY | MODIFY | 42, 42, 42 (36-72) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 3/3 | 0, 0, 0 |

## Why it failed

- S3-PROMO-ENDING, run 20261114T130953-8c8f5f, decision: decided MODIFY, expected ACCEPT
- S3-PROMO-ENDING, run 20261114T130953-8c8f5f, action: 480 units, expected 0
- S3-PROMO-ENDING, run 20261114T131005-dfcd19, decision: decided MODIFY, expected ACCEPT
- S3-PROMO-ENDING, run 20261114T131005-dfcd19, action: 480 units, expected 0
- S3-PROMO-ENDING, run 20261114T131016-3fd690, decision: decided INVESTIGATE, expected ACCEPT
- S4-BUDGET, run 20261114T131029-23f0ad, validation: verifier findings: STOCKOUT_UNRESOLVED

## Cost and speed

- Mean turns per run: 5.3
- Mean tool calls chosen by the agent: 13.5
- Mean blocked or unjustified writes: 0.09
- Mean tokens per run: 22603 in, 614 out
- Mean latency per run: 10.8s (total 358s)
