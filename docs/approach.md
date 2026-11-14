# Approach

How the problem was broken down, what information the agent gets and why, how decisions are made, and where a human stays in charge.
For the components see [architecture.md](architecture.md), and for how the result is judged see [evaluation.md](evaluation.md).

## Contents

- [Breaking down the problem](#breaking-down-the-problem)
- [What a buyer needs to know, and the tool for each](#what-a-buyer-needs-to-know-and-the-tool-for-each)
- [How decisions are made](#how-decisions-are-made)
- [What the agent may and may not do](#what-the-agent-may-and-may-not-do)
- [When a human is involved](#when-a-human-is-involved)
- [Handling uncertainty and bad data](#handling-uncertainty-and-bad-data)
- [The prompt](#the-prompt)
- [Deliberate simplifications](#deliberate-simplifications)

## Breaking down the problem

A buyer's job is the same loop whatever starts it: something arrives, the buyer looks at the facts, decides, acts, and checks that the action worked.
The four assignment scenarios are four different starting points for that one loop.

| Assignment scenario | Trigger the agent receives | The question |
|---|---|---|
| 1. Purchase recommendation review | `RECOMMENDATION_REVIEW`: an upstream engine recommends buying N units | Accept, modify, reject, or investigate further? |
| 2. Supplier cannot fulfil | `SUPPLIER_EVENT`: a supplier confirms only part of a PO | Is the gap a problem, and if so, who covers it? |
| 3. Demand or forecast has changed | `DEMAND_ALERT`: recent sales are far above the forecast | Is the change real, a one-off, or explained by a promotion? |
| 4. Purchasing constraint | Any of the above, where a constraint (budget, MOQ against shelf life) blocks the obvious purchase | What is the best legal action, and who must be asked for the rest? |

There is no handler per scenario.
There is one agent, one prompt and one set of tools, and a scenario is a database plus a trigger.
The 11 test scenarios are variants of the four, and each group includes cases where the right answer is not to buy.
An agent that always buys, or always rejects, would pass a single happy-path test, so the variants test judgement and not activity.

The recommendation, the forecast and the inventory record can each be wrong, so the agent compares them with each other rather than trusting any one.
In S1-MODIFY the engine recommends 800 units because it forgot the stock on hand and the inbound PO.
In S1-INVESTIGATE the inventory record says zero even though a delivery landed two days ago.

## What a buyer needs to know, and the tool for each

Each read tool returns one category of information, and the category is recorded so the evaluation can check that the agent looked at what the decision needed.

| Information | Tool | Why a buyer needs it |
|---|---|---|
| The trigger | `get_recommendation`, `get_supplier_events` | What was proposed or reported, and the engine's stated reason. |
| Product facts | `get_product` | Case pack, shelf life, storage zone, review period and safety days. |
| Inventory | `get_inventory` | On-hand units, when they were last counted, and data-quality issues. |
| Demand history | `get_sales_history` | Daily sales plus 7-day mean and median, trend, outlier days and promotion days. |
| Forecast | `get_forecast` | The upstream expectation to compare with reality. |
| Promotions | `get_promotions` | A spike caused by a promotion that is ending must not be extrapolated. |
| Open purchase orders | `get_purchase_orders` | Inbound stock and its arrival dates, plus recent receipts. |
| Suppliers | `get_suppliers` | Cost, MOQ, lead time, listed capacity, approval status, on-time and fill rate. |
| Budget | `get_budget` | Category budget, spent, committed on open POs, remaining. |
| Storage | `get_storage` | Zone capacity, space used by other SKUs, this SKU's stock and inbound, free space. |
| Arithmetic | `plan_order` | Target stock, inventory position, net need, suggested quantity, every limit and which one binds, stockout day without an order. |

The model gets the trigger (its type, its ids and the SKU) and the tools, and nothing else (D61).
It decides what to read and in what order.
An earlier version preloaded a snapshot of facts.
Models re-read it anyway, and it hid whether the agent knew what to look at.
The evaluation scores information gathering on what the model itself read, and reports repeat reads separately.

## How decisions are made

### Maths in code, judgement in the model

The replenishment maths is the classic order-up-to policy, simple enough to check by hand.

```text
target_stock       = daily_demand x (lead_time + review_period + safety_days)
inventory_position = on_hand + open inbound POs (confirmed quantity if the supplier answered, else ordered)
net_need           = max(0, target_stock - inventory_position)
order_quantity     = net_need rounded up to a case pack, and at least the MOQ (0 if there is no need)
```

The caller chooses `daily_demand`, because "trust the forecast or recent sales?" is judgement.
Given that choice, the rest is arithmetic, so it is code.
The prompt does not tell the agent how to choose (D60).
The demand statistics give it the median, outlier days and promotion days to decide with.

The trace records which demand the agent chose and why, and the verifier re-checks the result at that demand.

A real tool result for S1-MODIFY at 40 units a day from the primary supplier:

```text
target_stock 600, inventory_position 420, net_need 180, suggested_qty 192
limits: budget 984, storage 264, supplier_capacity 9984, binding "storage" (max 264)
stockout_without_order: day 10, arrival day 5
```

The engine's 800 ignores 220 on hand and 200 already inbound.
The right order is 192 (eight cases of 24), and 800 would also exceed the free storage.

### Median, not mean

Recent demand is summarised with the 7-day median, and a day is an outlier when it sells more than 2.5 times that median.
A single bulk order (one day at 260 units in a week of about 28) would drag the 7-day mean to about double the forecast while the median stays near normal, and `get_sales_history` reports that day as an outlier.
In S3-PROMO-ENDING the spike is real but explained by a promotion that ends tomorrow, so the right demand to plan for is the post-promotion forecast; a baseline that plans off the 7-day mean instead buys 480 units nobody needs, and it is in the demo.
In S3-SUSTAINED-SPIKE sales rise steadily with no promotion and no outlier, so the median moves too and a purchase is right.

### Decision vocabulary

| Decision | Meaning |
|---|---|
| `ACCEPT` | The plan as given is right. For a recommendation, the agent placed the recommended PO. For a supplier message, it accepted the partial confirmation and no extra PO is needed. For an alert, nothing needs to change. |
| `MODIFY` | The agent changed the plan: a different quantity, a different supplier, or an extra PO. |
| `REJECT` | Nothing should be bought. |
| `INVESTIGATE` | The data cannot support a decision. The agent escalated an investigation and bought nothing. |

The decision also states `new_units`, the units that will arrive from POs the agent created or increased (the supplier's confirmed quantity, not what was asked for), so the claim can be checked against the database.

### Choosing a supplier

When several suppliers work, the agent weighs lead time, reliability and cost and says why.
The data sets traps on purpose.
In the supplier scenarios the cheapest option is not an approved supplier, another is cheap but slow and unreliable, and the primary supplier has nothing more to give.
An unapproved supplier is blocked by the validator whatever the model thinks, and a slow supplier whose delivery lands after a projected stockout gets a warning that must be justified.

## What the agent may and may not do

Allowed, through the write tools:

| Tool | Effect |
|---|---|
| `create_po` | A new PO, optionally linked as a top-up with `parent_po_id`. |
| `modify_po` | Change the quantity of a PO before the supplier has confirmed it. |
| `accept_partial_confirmation` | Take what the supplier can ship on a partially confirmed PO. |
| `cancel_po` | Cancel an open PO. |
| `escalate_to_human` | Ask a person to investigate, raise a budget, or handle a supplier problem. |
| `submit_decision` | Finish the run with a structured, checkable answer. |

Not possible, enforced in code and not by asking nicely:

- ordering from an unapproved supplier, or one that does not sell the SKU,
- breaking a case pack, a supplier MOQ, a supplier's listed capacity, the category budget, the free storage or a perishable's shelf life,
- sending a PO above $2,000 to a supplier before a human approves it,
- rewriting a PO after the supplier has confirmed it (the agent cancels it or adds a linked top-up instead),
- touching another node's POs, or probing whether they exist,
- seeing the supplier's real availability before the supplier answers,
- creating an `APPROVAL` or `VERIFICATION_FAILED` escalation (those belong to the pipeline and the verifier),
- continuing to write after the same failure has repeated three times.

## When a human is involved

| Situation | Mechanism |
|---|---|
| A valid PO is worth more than $2,000 | The PO is written as `PENDING_APPROVAL`, the supplier is not contacted, and an `APPROVAL` item appears in the UI queue. Approve sends it to the supplier and returns the supplier's answer. Reject cancels it. |
| The data cannot be trusted | The agent raises an `INVESTIGATION` escalation and does not buy. |
| The budget is too small for what is needed | The agent buys what the budget allows if that prevents a stockout, and raises `BUDGET_INCREASE` for the rest. |
| No approved supplier can cover the need in time | The agent raises `SUPPLIER_ISSUE`. Escalating alone is a weaker answer when another approved supplier could have covered the gap, and the evaluation scores it that way. |
| The same action fails three times | Writes are locked, so the only way forward is `escalate_to_human`. |
| The final verification still fails after one retry, or the run never reaches a decision | The run is flagged with a `VERIFICATION_FAILED` escalation. |

## Handling uncertainty and bad data

- **Stale or contradictory inventory.** `get_inventory` compares the on-hand record with goods received since the last count minus sales since, and raises `INVENTORY_RECORD_SUSPECT` when stock is below half of what the receipts imply.
  Code spots the contradiction because small models would likely miss it, and the agent decides what to do about it.
- **Outliers and promotions.** Demand statistics expose the median, outlier days and promotion days so the agent can tell a real shift from noise.
- **Supplier reliability.** Listed capacity is a catalog figure, and only the supplier's confirmation is binding.
  The agent sees on-time and fill rates, and a supplier below 80% on time triggers a warning.
- **Unusual but legal choices.** Excess cover, arrival after a projected stockout and unreliable suppliers are warnings.
  They are allowed, but only on the record: the write needs a justification that is stored in the PO notes and the audit log.
- **The agent's own claims.** The verifier recomputes what will arrive and compares it with what the agent said.

## The prompt

There is one general system prompt (D60).
It describes the job, the loop (investigate, decide, act, check, submit) and the output contract, and nothing about how to solve a particular kind of case.
An earlier version taught rules that each matched one scenario group: plan on the median after a sustained shift, ignore a one-off outlier or an ending promotion, top up a short PO from another supplier, buy what the budget allows and escalate the rest.
Those were the answer key written as advice, so they were removed.
The write tools' descriptions carry their own contract (BLOCKED, NEEDS_JUSTIFICATION, PENDING_APPROVAL, the supplier's confirmation), and the `submit_decision` schema defines the decision labels.
Tests check that the prompt names no scenario, SKU, supplier or PO, names no tool except `plan_order` and `submit_decision`, and contains none of a short list of scenario-shaped words.
They also check that the trigger message does not leak the worked example.

## Deliberate simplifications

| Simplification | Real world | Why it is acceptable here |
|---|---|---|
| One SKU per PO | POs have many lines | Line-level logic adds no decision insight. |
| Storage measured in units | Pallets or cubic metres | Same constraint shape. |
| Other SKUs' storage is one number | Full assortment | The agent reasons about one SKU at a time. |
| Flat daily forecast | Weekly seasonality | Keeps the maths hand-checkable. |
| All scenarios at one dark store | Many nodes | Stock transfers between nodes are a listed extension. |
| Order-up-to safety days | Statistical safety stock | Harder to explain and it changes no decision in these scenarios. |
| A deterministic mock supplier | Variable, negotiable suppliers | A confirmation that depends only on stored availability makes loop 2 reproducible. |
| Fixed approval limit | Limits by role and category | One threshold shows the pattern. |
