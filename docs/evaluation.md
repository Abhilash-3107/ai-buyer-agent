# Evaluation

The assignment says it cares about the quality of the evaluation approach, not about a sophisticated framework.
So every score here is a deterministic check on the final database and the tool calls, with its reason written next to it.
There is no model judge.
Two deliberately dumb baselines are scored by the same code, so the evaluation itself is shown to tell good behaviour from bad.

## Contents

- [Scenarios](#scenarios)
- [Ground truth: bands, not exact numbers](#ground-truth-bands-not-exact-numbers)
- [The six checks](#the-six-checks)
- [Do-nothing variants](#do-nothing-variants)
- [Baselines](#baselines)
- [Repeats and temperature](#repeats-and-temperature)
- [Results](#results)
- [What the real runs taught us](#what-the-real-runs-taught-us)
- [Run the same evaluation on a model](#run-the-same-evaluation-on-a-model)
- [What the evaluation does not measure](#what-the-evaluation-does-not-measure)

## Scenarios

The four assignment scenarios are implemented as 11 variants, defined in `backend/app/scenarios/catalog.py`.
Each one is a function that fills a fresh database, plus a trigger and an `Expected` block with the hand-worked numbers.

| Scenario | Group | Title | Expected decision | New-buy band (units) | What it tests |
|---|---|---|---|---|---|
| `S1-MODIFY` | 1 Recommendation review | Recommendation ignores stock on hand and inbound PO | MODIFY | 168 to 240 | The engine ignores stock on hand and an inbound PO, so 800 units is far too much and would also break free storage. The right order is a few cases that cover the net need. |
| `S1-ACCEPT` | 1 Recommendation review | Recommendation is correct | ACCEPT | 456 to 504 | The recommendation is correct (a whole number of cases, inside budget and storage). The agent must verify it and not invent a change. |
| `S1-REJECT` | 1 Recommendation review | Already overstocked - standing order should not fire | REJECT | 0 | A fixed standing order of 480 (a valid PO on its own) fires although stock plus inbound already cover about five weeks. Nothing should be bought. |
| `S1-INVESTIGATE` | 1 Recommendation review | Inventory record contradicts recent receipts and sales | INVESTIGATE and an INVESTIGATION escalation | 0 | The inventory record says zero, but a delivery two days ago and continued sales contradict it. The agent should request a count and not buy on a record it cannot trust. |
| `S2-SOURCE-ELSEWHERE` | 2 Supplier cannot fulfil | Short shipment leaves a gap - source the remainder from an alternate | MODIFY | 90 to 220 | The primary supplier ships half of a PO and has nothing more. The gap must come from an approved, fast alternate. Traps: the cheapest supplier is not approved, and another is cheap but slow and unreliable. |
| `S2-ACCEPT-SHORT` | 2 Supplier cannot fulfil | Short shipment, but existing stock already covers demand | ACCEPT | 0 | Same short shipment, but existing stock already covers demand. Accept the partial confirmation and buy nothing. |
| `S2-ALT-ALSO-SHORT` | 2 Supplier cannot fulfil | Alternate supplier ALSO short-confirms - agent must recover | MODIFY | 90 to 220 | The alternate's catalog says 1,000 units, but it confirms only 40. The agent must notice the shortfall in the supplier's answer and cover the rest from another approved supplier. Exercises loops 2 and 3. |
| `S3-SUSTAINED-SPIKE` | 3 Demand changed | Sustained demand increase - open PO no longer enough | MODIFY | 180 to 650 | Sales rose steadily to about two and a half times the forecast with no promotion. The open PO is no longer enough, so the plan must change. |
| `S3-PROMO-ENDING` | 3 Demand changed | Spike is explained by a promotion that ends tomorrow | ACCEPT | 0 | The spike is explained by a promotion that ends tomorrow. Do not extrapolate it. |
| `S4-BUDGET` | 4 Purchasing constraint | Need is real but exceeds the remaining category budget | MODIFY and a BUDGET_INCREASE escalation | 120 to 396 | The need is real but the category budget allows only part of it. Buy what fits, raise a budget escalation for the rest, and note the PO is above the approval limit so a human approves it. |
| `S4-MOQ-VS-SHELF-LIFE` | 4 Purchasing constraint | Primary supplier's MOQ would force buying more than can sell before expiry | MODIFY | 36 to 72 | The primary supplier's MOQ would force a purchase that cannot sell before the shelf life ends. A different approved supplier with a small MOQ is the better buy. |

Groups: 1 is recommendation review, 2 is supplier cannot fulfil, 3 is demand or forecast changed, 4 is purchasing constraint.

## Ground truth: bands, not exact numbers

Reasonable buyers differ.
One plans with the alternate supplier's 3-day lead time and another with the primary's 6-day one, or uses the 7-day average where another uses the latest day.
So each scenario's expected answer is a band and a set of conditions, not a single quantity:

- the decision (`ACCEPT`, `MODIFY`, `REJECT` or `INVESTIGATE`),
- a band for the units that will arrive from POs the agent creates or increases,
- the suppliers that are acceptable, when the agent buys,
- an escalation that must be raised, when one is required,
- the information categories the agent must have looked at.

The bands come from the order-up-to formula worked by hand and written next to each scenario (`worked_example`).
For S1-MODIFY the target is 600, the position is 420 and the net need is 180, which rounds to 192 in cases of 24, and the band allows for planning assumptions that differ a little (168 to 240).
The expected answers are shown in the UI next to the agent's answer, and they are the same data the scorer uses.

## The six checks

The checks are the assignment's own list of questions.
Each check has a pass or fail, an `applicable` flag, and a reason with the numbers, such as "336 units, expected 0".

| # | Question from the assignment | Check | Passes when |
|---|---|---|---|
| 1 | Was the decision correct? | `decision` | The submitted decision equals the expected decision. A run that never submitted fails. |
| 2 | Did the agent obtain the necessary information? | `information` | The agent itself read every category in `required_info` successfully. Nothing is preloaded (D61). The report also counts repeat reads: reads that repeat an earlier successful one with the same arguments. They are reported, never failed on. |
| 3 | Did it respect the relevant constraints? | `constraints` | Every open PO the agent created or modified passes the validator with no errors, at the daily demand the agent recorded for it, and went to an approved supplier that sells the SKU. |
| 4 | Did it take the appropriate action? | `action` | The run finished (`DECIDED`), the new-buy units are inside the band, every supplier used is in the allowed list, and any required escalation kind was raised. |
| 5 | Did it validate the result? | `validation` | The run ended with `submit_decision` and the final verifier pass has no findings: claims match the database, shortfalls are handled, no unaddressed stockout. |
| 6 | What happens when the first action does not work? | `recovery` | Applicable only when some write of the agent was `BLOCKED`, `NEEDS_JUSTIFICATION` or came back with a supplier shortfall. Passes if each such failure was followed by a successful write or an escalation, or if the agent rightly gave up (the run ended `DECIDED` and the action check passed, for example a refused PO followed by a correct `REJECT`). |

Details that matter:

- **New-buy units** are the units expected to arrive on POs the agent created, plus the increase on POs it modified.
  The supplier's confirmed quantity counts where the supplier answered, and the ordered quantity otherwise.
  A PO held for approval counts as ordered.
  A cancelled PO counts for nothing.
- **A run passes** when every applicable check passes.
  **A scenario passes** when every repeat passes.
- **Constraints are checked again at the end**, independently of the pipeline that enforced them, so the check would catch a bug in the guardrails as well as a bad plan.
- The scorer never calls a model.
  It reads only the run database, the tool-call records and the agent's result.
- Cost and speed are reported next to the scores: turns, tool calls chosen by the agent, blocked writes, tokens and latency.

The scenarios were designed so that each question can fail on its own.
S1-INVESTIGATE fails `action` if the agent buys on a record the data contradicts.
S2-ALT-ALSO-SHORT exercises `recovery`, because the first order always comes back short.
S4-BUDGET fails `action` if the agent buys nothing, or buys but does not raise the budget escalation for the rest.

## Do-nothing variants

An agent that always modifies the plan would pass a single happy-path test.
Five of the 11 scenarios expect `ACCEPT`, `REJECT` or `INVESTIGATE` instead of `MODIFY`, and four of those expect no new purchase at all (`S1-REJECT`, `S1-INVESTIGATE`, `S2-ACCEPT-SHORT`, `S3-PROMO-ENDING`).
The agent has to know when not to buy, and almost half of the scenarios measure exactly that.
S3-PROMO-ENDING looks like the sustained spike on the alert (sales far above the forecast) but calls for no change, and S2-ACCEPT-SHORT looks like the other short-shipment scenarios but existing stock already covers demand.

S2-ALT-ALSO-SHORT has one more subtlety.
Escalating alone does not pass when another approved supplier can cover the gap (Rapido can, with MOQ 20 and 4 days), because handing a solvable problem to a person is a weaker answer.
Escalation is the right move only when no approved supplier can cover the need in time.

## Baselines

Two policies stand in for the model and answer the loop's model calls with a fixed plan of tool calls.
So the prompt, the write pipeline, the verifier and the trace are exactly the ones the real agent gets, and the scorer is unchanged.
Like the agent, a baseline gets only the trigger and must read what it uses: `rubber_stamp` reads the sales history and, for a recommendation, the recommendation itself.

| Baseline | Behaviour |
|---|---|
| `rubber_stamp` | Does what the trigger implies without thinking. Recommendation: `create_po` for the recommended quantity and supplier. Supplier short: accept the partial confirmation. Demand alert: plan an order at the 7-day mean from the primary supplier. Always decides `ACCEPT`. |
| `do_nothing` | Never writes anything and decides `REJECT` every time. |

If approving everything scored well, the evaluation would be broken.
Both baselines score 0 out of 11.
Neither investigates, so both fail `information` everywhere.
Their decisions are still right sometimes: `do_nothing` decides REJECT correctly on `S1-REJECT`, and `rubber_stamp` makes the right call on `S2-ACCEPT-SHORT`.
Before D61 the preload covered the information check for them, and each passed exactly that one scenario.

## Repeats and temperature

A single lucky run proves little, so the evaluator can repeat every scenario (`--repeats N`).
The report shows how often each scenario produced the same decision across repeats.
Evaluation runs use temperature 0 unless `LLM_TEMPERATURE` is set, so repeats measure what non-determinism remains.
Runs are sequential, one local model at a time, and the result files are rewritten after every finished run, so a long evaluation can be inspected while it is still going.

## Results

<!-- RESULTS:START -->
Generated from the JSON reports in `docs/eval/`.
A scenario passes only when every repeat passes.

| Name | Kind | Runs | Scenarios passed | Runs passed | decision | information | constraints | action | validation | recovery |
|---|---|---|---|---|---|---|---|---|---|---|
| [gpt-6-luna](eval/gpt-6-luna.md) | model | 33 (11 x 3) | 9/11 | 27/33 | 30/33 | 33/33 | 33/33 | 28/33 | 30/33 | 7/7 |
| [rubber_stamp](eval/rubber_stamp.md) | baseline | 11 | 0/11 | 0/11 | 3/11 | 0/11 | 11/11 | 3/11 | 5/11 | 0/4 |
| [do_nothing](eval/do_nothing.md) | baseline | 11 | 0/11 | 0/11 | 1/11 | 0/11 | 11/11 | 3/11 | 4/11 | n/a |

Runs passed per scenario:

| Scenario | gpt-6-luna | rubber_stamp | do_nothing |
|---|---|---|---|
| S1-MODIFY | 3/3 | 0/1 | 0/1 |
| S1-ACCEPT | 3/3 | 0/1 | 0/1 |
| S1-REJECT | 3/3 | 0/1 | 0/1 |
| S1-INVESTIGATE | 3/3 | 0/1 | 0/1 |
| S2-SOURCE-ELSEWHERE | 3/3 | 0/1 | 0/1 |
| S2-ACCEPT-SHORT | 3/3 | 0/1 | 0/1 |
| S2-ALT-ALSO-SHORT | 3/3 | 0/1 | 0/1 |
| S3-SUSTAINED-SPIKE | 3/3 | 0/1 | 0/1 |
| S3-PROMO-ENDING | 0/3 | 0/1 | 0/1 |
| S4-BUDGET | 0/3 | 0/1 | 0/1 |
| S4-MOQ-VS-SHELF-LIFE | 3/3 | 0/1 | 0/1 |
<!-- RESULTS:END -->

How to read the table:

- Each row is one evaluated model or baseline.
  The report for each is in this repository under `docs/eval/`, with one row per scenario, a reason for every failed check and the run ids.
- A column such as `action` shows passed runs over the runs where that check applied.
- Every report is reproducible: `docs/eval/<name>.json` holds the full score cards, and the Markdown report is rendered from it.
- Run ids refer to databases and traces in `backend/data/runs/`, which is git-ignored.
  Re-running the command in the next section regenerates them.

What the baselines show:

- `rubber_stamp` passes `constraints` in 11 of 11 runs.
  It does the naive thing, but the validator refuses its illegal orders (in S1-MODIFY the recommended 800 units is blocked, so 0 units are bought, and the `action` check says "0 units, expected 168-240").
  The guardrails, not the model, enforce the rules.
- Legal is not the same as right.
  In S1-REJECT `rubber_stamp` places the engine's standing order of 480, which is a valid PO, so `constraints` passes and `action` fails with "480 units, expected 0". 
  In S3-PROMO-ENDING it plans off the promotion-inflated mean and does the same with 480 units.
- `do_nothing` passes `constraints` in 11 of 11 runs for the opposite reason: it never writes, so it can never break a rule.
  It still fails the scenarios that need a purchase, and `recovery` is never applicable to it because no write ever fails.
- A model that scores well must therefore do what neither baseline can: investigate, choose a sensible quantity, and recover when the world pushes back.

## What the real runs taught us

<!-- FINDINGS -->

### 1. The server silently truncated the prompt

The first live run of S1-MODIFY on a local model ended `MAX_STEPS` after 30 turns, with the model re-reading data it already had and then calling `get_product` with the SKU `placeholder_sku` (run id `20261111T181618-aa2177`).
That looked like poor model judgement.
The trace said otherwise: the first turn reported exactly 4096 input tokens, which is Ollama's default context window, and the next turn reported fewer (2411), although the conversation only grows.
The first request is larger than 4096 tokens (about 4,200 input tokens in later traces), so the server dropped the start of the conversation, and the model never saw its instructions or the preloaded snapshot.

What changed:

- `ollama/Modelfile.qwen3.5-4b` sets `num_ctx 32768`, and the README tells users to build the model from it.
- A truncation guard in the loop stops the run with outcome `CONTEXT_TRUNCATED` and a clear message if the reported input tokens equal a common context size or drop from one turn to the next, so a blind model can never act on the database.

The lesson is that a silent infrastructure failure looked exactly like bad model judgement, and the per-turn token counts in the trace are what told them apart.

### 2. Small models write tool calls as text, and submit before acting

Local models of this size often answer in text instead of using the tool-calling interface.
They also submit a decision before doing the work.
In a development run of S1-MODIFY (run id `20261111T183213-bb9ff5`) the model wrote its final decision as JSON text: `MODIFY`, `new_units` 192, "PO-1101: Increased from 200 to 392 units".
It had never called `create_po` or `modify_po`, so no such PO existed.

Two mechanisms caught it:

- Text recovery.
  A reply that holds exactly one JSON object that is a known tool call or a decision is executed as that call, traced as `recovered_tool_call`.
  Anything else gets a nudge to use the tool interface.
- The verifier.
  It returned `CLAIM_MISMATCH` (claimed 192 units, the database expects 0) and `STOCKOUT_UNRESOLVED`.
  The model then escalated instead of buying and resubmitted a different decision, which failed `DECISION_ACTION_MISMATCH` and left the run flagged for a human.

The machinery worked: a false claim never reached a clean pass, and nothing illegal was written.
The judgement was weak, and that is what the evaluation measures.

### 3. A strong model names the promotion, then plans as if it lasts (S3-PROMO-ENDING)

gpt-6-luna failed S3-PROMO-ENDING in all three repeats, and its own key factors show why.
In every run it wrote that all seven elevated sales days overlap PROMO-77, which ends the next day.
In two runs it then called `plan_order` at 73 units a day, the promotional rate, and raised PO-3003 from 200 to 480 and to 672 units (runs `20261114T123054-b0711b` and `20261114T123104-7ada82`).
The second run's summary even says demand "may normalize after it ends".
After the two remaining promotion days (about 146 units), the 420 on hand plus the 200 inbound still leave about 474 units, above the 375-unit target at the normal 25 a day, so nothing needed to change.
The third run planned at 25, 73 and the 28-day mean of 37, could not choose, and escalated an `INVESTIGATION` without buying (run `20261114T123114-174b89`).
That is a safe answer but the wrong label: the data was consistent, so there was nothing to investigate.

All three orders were legal, so `constraints` and `validation` passed, and only `decision` and `action` caught them.
This is the case the "legal is not the same as right" check exists for: the rules cannot tell a promotional rate from a sustained one, and the model's choice of daily demand is the judgement being measured.

### 4. Escalating instead of buying what the budget allows (S4-BUDGET)

gpt-6-luna failed S4-BUDGET in all three repeats in the same way.
It read everything, planned at the right 60 units a day, and saw that `plan_order` capped the order at 396 units by budget, against a net need of 570.
It raised a correct `BUDGET_INCREASE` escalation with the numbers, and then bought nothing.
Its summary gives the reason: the largest affordable order "would not cover planned net need".

That reasoning is wrong for a buyer.
The 7-day lead time means an order placed today arrives on the day stock runs out, so every day spent waiting for a budget answer is a day of stockout.
396 units on top of the 450 on hand cover about 14 of the 17 days the plan targets, so the gap is the safety stock, not the stock itself.
And the 396-unit PO ($2,376) is above the $2,000 approval limit, so a person would have seen it next to the budget request anyway: buying it now risks no unauthorised spend.

The verifier refused both of its labels, `INVESTIGATE` (no investigation was raised) and `MODIFY` (no PO changed), and the run was flagged for a human.
The scorer marks the run wrong on `action` (0 units, expected 120 to 396).

## Run the same evaluation on a model

The evaluator takes the endpoint and key from the environment and the model name from `LLM_MODEL` or `--model`.
A report is written for the model under `docs/eval/<model>.json` and `.md`.
Run it from the `backend` folder.

```bash
# a local model through Ollama (see the README for building the 32k-context variant)
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_API_KEY=ollama
uv run buyer-eval --model buyer-qwen3.5-4b --repeats 3

# an OpenAI model (replace the placeholder with the model name you have access to)
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_API_KEY=<your key>
uv run buyer-eval --model <openai-model> --repeats 3
```

Useful variations:

```bash
# a subset of scenarios
uv run buyer-eval --model buyer-qwen3.5-4b --scenarios S1-MODIFY,S2-ALT-ALSO-SHORT

# the baselines (no model, no key)
uv run buyer-eval --baseline rubber_stamp
uv run buyer-eval --baseline do_nothing

# write somewhere else instead of docs/eval
uv run buyer-eval --baseline do_nothing --out /tmp/eval-check

# one comparison table across saved results
uv run buyer-eval --compare ../docs/eval/*.json
```

`--compare` writes a `README.md` into the output directory (`docs/eval` by default) with every model and baseline side by side and a per-scenario matrix.
The Eval tab in the UI reads the same `docs/eval/*.json` files.

## What the evaluation does not measure

- **Explanation quality.** The agent's key factors and summary are shown in the UI and quoted in reports, but they are not scored.
  A model judge would add noise, and the sensible extension is a judge calibrated against a few hand-graded runs.
- **Anything outside these 11 situations.** The bands encode one reasonable buyer's view of each, so the results say how the agent behaves on this world, not on every purchasing problem.
- **Cost in money.** Tokens and latency are reported, but not a price per run.
- **Concurrency and scale.** Runs are sequential and the infrastructure is demo-scale.
