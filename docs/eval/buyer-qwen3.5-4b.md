# Evaluation: buyer-qwen3.5-4b

Agent version: git fec40a7, prompt 2cf70775b782.

Every score is a deterministic check on the final database and the tool calls, with its reason written next to it.
14 runs: 5 scenarios x 3 repeat(s).

## Headline

- Scenarios passed (every repeat passed): **2/5**
- Runs passed: **6/14 (43%)**
- Run outcomes: CONTEXT_TRUNCATED x2, DECIDED x12

| Check | Passed |
|---|---|
| decision | 12/14 (86%) |
| information | 8/14 (57%) |
| constraints | 14/14 (100%) |
| action | 12/14 (86%) |
| validation | 12/14 (86%) |
| recovery | n/a |

## Scenarios

A check shows ✓ when every repeat passed, ✗ when none did, k/n when mixed, and - when it did not apply.
Consistency is how many runs gave the most common decision.
Repeat reads counts, per run, the reads that repeated an earlier successful read with the same arguments.

| Scenario | Expected | Got | New units (band) | decision | information | constraints | action | validation | recovery | Consistency | Repeat reads |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1-MODIFY | MODIFY | MODIFY | 192, 192, 192 (168-240) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 3/3 | 0, 0, 0 |
| S1-ACCEPT | ACCEPT | ACCEPT | 480, 480, 480 (456-504) | ✓ | ✗ | ✓ | ✓ | ✓ | - | 3/3 | 0, 0, 0 |
| S1-REJECT | REJECT | REJECT | 0, 0, 0 (0-0) | ✓ | ✗ | ✓ | ✓ | ✓ | - | 3/3 | 0, 0, 0 |
| S1-INVESTIGATE | INVESTIGATE | INVESTIGATE | 0, 0, 0 (0-0) | ✓ | ✓ | ✓ | ✓ | ✓ | - | 3/3 | 2, 2, 2 |
| S2-SOURCE-ELSEWHERE | MODIFY | none | 500, 500 (90-220) | ✗ | ✓ | ✓ | ✗ | ✗ | - | 2/2 | 0, 0 |

## Why it failed

- S1-ACCEPT, run 20261114T123722-10ec8f, information: never read: forecast
- S1-ACCEPT, run 20261114T123954-236fa7, information: never read: forecast
- S1-ACCEPT, run 20261114T124227-b4839f, information: never read: forecast
- S1-REJECT, run 20261114T124457-7bcfa5, information: never read: forecast
- S1-REJECT, run 20261114T125100-ba967b, information: never read: forecast
- S1-REJECT, run 20261114T125657-0636e3, information: never read: forecast
- S2-SOURCE-ELSEWHERE, run 20261114T131438-d1c105, decision: no decision was submitted (run ended CONTEXT_TRUNCATED), expected MODIFY
- S2-SOURCE-ELSEWHERE, run 20261114T131438-d1c105, action: run did not finish (CONTEXT_TRUNCATED)
- S2-SOURCE-ELSEWHERE, run 20261114T131438-d1c105, validation: the run ended CONTEXT_TRUNCATED without submit_decision
- S2-SOURCE-ELSEWHERE, run 20261114T132803-74cfee, decision: no decision was submitted (run ended CONTEXT_TRUNCATED), expected MODIFY
- S2-SOURCE-ELSEWHERE, run 20261114T132803-74cfee, action: run did not finish (CONTEXT_TRUNCATED)
- S2-SOURCE-ELSEWHERE, run 20261114T132803-74cfee, validation: the run ended CONTEXT_TRUNCATED without submit_decision

## Cost and speed

- Mean turns per run: 5.7
- Mean tool calls chosen by the agent: 12.6
- Mean blocked or unjustified writes: 0.00
- Mean tokens per run: 29764 in, 4941 out
- Mean latency per run: 317.8s (total 4450s)
