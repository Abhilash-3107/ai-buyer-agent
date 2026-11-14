import { useState } from "react";
import { api, ApiError, type Verb } from "../api";
import type { Check, Escalation, PurchaseOrder, RunSummary, Scenario } from "../types";
import { bandWords } from "../lib/derive";
import { count, money } from "../lib/format";
import { checkLabel, decisionWord, escalationAsk, escalationKind, humanize, poStatus } from "../lib/words";
import { Cross, Tick } from "./Icons";
import { Empty } from "./States";
import { WithIds } from "./Text";

interface Props {
  scenario: Scenario;
  summary: RunSummary | null;
  hasRun: boolean;
  runId: string | null;
  sku: string | null;
  onChanged: () => void;
}

export function Outcome({ scenario, summary, hasRun, runId, sku, onChanged }: Props) {
  const running = hasRun && summary?.status !== "finished";
  // The queue leads the left column for as long as the run has any approval (the buyer's most frequent job), so a decision made there
  // does not make the card jump away from under the buyer's pointer.
  const approvals = (summary?.escalations ?? []).filter((e) => e.kind === "APPROVAL");
  const queue = <Queue summary={summary} hasRun={hasRun} runId={runId} onChanged={onChanged} key="queue" />;
  return (
    <div className="outcome-grid">
      <div className="col">
        {approvals.length > 0 && queue}
        <DecisionCard scenario={scenario} summary={summary} hasRun={hasRun} running={running} />
        <Checks summary={summary} hasRun={hasRun} running={running} />
      </div>
      <div className="col">
        <PoTable summary={summary} hasRun={hasRun} sku={sku} />
        {approvals.length === 0 && queue}
      </div>
    </div>
  );
}

/* ---------- decision, agent next to expected ---------- */

function DecisionCard({ scenario, summary, hasRun, running }: { scenario: Scenario; summary: RunSummary | null; hasRun: boolean; running: boolean }) {
  const exp = scenario.expected;
  const d = summary?.decision ?? null;
  const card = summary?.scorecard ?? null;
  const decisionCheck = card?.checks.find((c) => c.name === "decision");
  const units = card?.new_buy_units ?? d?.new_units ?? null;
  const inBand = units !== null && units >= exp.new_buy_qty[0] && units <= exp.new_buy_qty[1];
  const agentPos = (summary?.purchase_orders ?? []).filter((p) => p.created_by === "agent");
  const agentSuppliers = [...new Set(agentPos.map((p) => p.supplier_id))];
  const agentEsc = [...new Set((summary?.escalations ?? []).filter((e) => !["APPROVAL", "VERIFICATION_FAILED"].includes(e.kind)).map((e) => escalationKind(e.kind)))];
  const settled = !!summary && !running && summary.outcome === "DECIDED";
  const dash = <span className="muted">-</span>;
  const wait = !hasRun ? "Not run yet" : running ? "Waiting" : "-";

  return (
    <section className="panel" aria-labelledby="decision-h">
      <div className="panel-head">
        <h2 id="decision-h">Decision</h2>
        <p className="meta">{hasRun ? "Agent against the expected answer" : "The expected answer"}</p>
      </div>
      <div className="compare">
        <span className="h" />
        <span className="h">Agent</span>
        <span className="h">Expected</span>

        <span className="row-label">Decision</span>
        <span className="val">
          {d ? decisionWord(d.decision) : <span className="muted" style={{ fontWeight: 400 }}>{wait}</span>}
          {settled && decisionCheck && (decisionCheck.passed ? <Tick /> : <Cross />)}
          {settled && decisionCheck && <span className="sr-only">{decisionCheck.passed ? "matches" : "differs"}</span>}
        </span>
        <span className="val">{decisionWord(exp.decision)}</span>

        <span className="row-label">New buy</span>
        <span className="val num">
          {units !== null ? `${count(units)} units` : <span className="muted" style={{ fontWeight: 400 }}>{wait}</span>}
          {settled && units !== null && (inBand ? <Tick /> : <Cross />)}
          {settled && units !== null && <span className="sr-only">{inBand ? "inside the band" : "outside the band"}</span>}
        </span>
        <span className="val num">{exp.new_buy_qty[1] === 0 ? "0 units" : bandWords(exp.new_buy_qty)}</span>

        <span className="row-label">Suppliers</span>
        <span className="val stack">
          {settled || agentSuppliers.length ? (agentSuppliers.length ? agentSuppliers.map((s) => <span key={s} className="mono">{s}</span>) : <span className="muted" style={{ fontWeight: 400 }}>None</span>) : dash}
        </span>
        <span className="val stack">
          {exp.allowed_suppliers?.length ? exp.allowed_suppliers.map((s) => <span key={s} className="mono">{s}</span>) : <span className="muted" style={{ fontWeight: 400 }}>Any</span>}
        </span>

        <span className="row-label">Escalation</span>
        <span className="val">{settled ? (agentEsc.length ? agentEsc.join(", ") : <span className="muted" style={{ fontWeight: 400 }}>None</span>) : dash}</span>
        <span className="val">{exp.escalation ? escalationKind(exp.escalation) : <span className="muted" style={{ fontWeight: 400 }}>None</span>}</span>
      </div>

      {d && (
        <>
          {d.summary && <p className="decision-summary">{d.summary}</p>}
          <ul className="factor-list list-none">
            {d.key_factors.map((f) => (
              <li key={f}>{f}</li>
            ))}
            <li className="num">
              Confidence {d.confidence}
              {d.daily_demand_used !== null && d.daily_demand_used !== undefined ? `, demand used ${d.daily_demand_used} units a day` : ""}
            </li>
          </ul>
        </>
      )}
      <details className="disclosure">
        <summary>How the expected answer is worked out</summary>
        <p>{exp.worked_example}</p>
      </details>
    </section>
  );
}

/* ---------- checks ---------- */

function Checks({ summary, hasRun, running }: { summary: RunSummary | null; hasRun: boolean; running: boolean }) {
  const card = summary?.scorecard ?? null;
  const applicable = card?.checks.filter((c) => c.applicable) ?? [];
  const passed = applicable.filter((c) => c.passed).length;
  return (
    <section className="panel" aria-labelledby="checks-h">
      <div className="panel-head">
        <h2 id="checks-h">Checks</h2>
        {card && <p className="meta num">{passed} of {applicable.length} passed</p>}
      </div>
      {card ? (
        <div className="checks">
          {card.checks.map((c) => (
            <CheckRow key={c.name} check={c} />
          ))}
        </div>
      ) : (
        <Empty>{!hasRun ? "Six checks score the run once it finishes." : running ? "Scored when the run finishes." : "No score was recorded for this run."}</Empty>
      )}
    </section>
  );
}

function CheckRow({ check }: { check: Check }) {
  return (
    <div className="check">
      {!check.applicable ? <span className="dash" aria-hidden="true" /> : check.passed ? <Tick /> : <Cross />}
      <div>
        <div className="check-name">
          {checkLabel(check.name)}
          <span className="sr-only">{!check.applicable ? ", not applicable" : check.passed ? ", passed" : ", failed"}</span>
          {!check.applicable && <span className="muted" style={{ fontWeight: 400 }}> (not applicable)</span>}
        </div>
        <p className="check-reason">{check.reason}</p>
      </div>
    </div>
  );
}

/* ---------- purchase orders ---------- */

function PoRow({ po }: { po: PurchaseOrder }) {
  const status = poStatus(po.status);
  return (
    <tr>
      <td>
        <span className="mono">{po.po_id}</span>
        {po.created_by !== "system" && <span className="muted small"> {po.created_by === "human" ? "by you" : "by agent"}</span>}
        <span className="sub">{po.supplier_name}</span>
      </td>
      <td>
        <span className={`pill ${status.tone === "neutral" ? "" : status.tone}`}>{status.label}</span>
        <span className="sub">arrives {po.expected_arrival}</span>
      </td>
      <td className="n num">
        {count(po.qty_ordered)}
        <span className="sub">{money(po.value)}</span>
      </td>
      <td className="n num">
        {po.qty_confirmed === null ? <span className="muted">-</span> : count(po.qty_confirmed)}
        <span className="sub">of {count(po.qty_ordered)}</span>
      </td>
    </tr>
  );
}

function PoTable({ summary, hasRun, sku }: { summary: RunSummary | null; hasRun: boolean; sku: string | null }) {
  const pos = summary?.purchase_orders ?? [];
  return (
    <section className="panel" aria-labelledby="po-h">
      <div className="panel-head">
        <h2 id="po-h">Purchase orders</h2>
        <p className="meta">
          {sku ? <><span className="mono">{sku}</span>, </> : null}
          {pos.length} {pos.length === 1 ? "order" : "orders"}
        </p>
      </div>
      {pos.length === 0 ? (
        <Empty>{!hasRun ? "Every open order for the product shows here, with what the agent adds." : "No purchase orders for this product."}</Empty>
      ) : (
        <div className="table-wrap">
          <table className="po-table">
            <thead>
              <tr>
                <th scope="col">Order</th>
                <th scope="col">Status</th>
                <th scope="col" className="n">Ordered</th>
                <th scope="col" className="n">Confirmed</th>
              </tr>
            </thead>
            <tbody>
              {pos.map((po) => (
                <PoRow key={po.po_id} po={po} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/* ---------- waiting for you ---------- */

interface Handled {
  busy?: Verb;
  message?: string;
  failed?: boolean;
}

function Queue({ summary, hasRun, runId, onChanged }: { summary: RunSummary | null; hasRun: boolean; runId: string | null; onChanged: () => void }) {
  const [handled, setHandled] = useState<Record<string, Handled>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const all = summary?.escalations ?? [];
  const open = all.filter((e) => e.status === "OPEN");
  const closed = all.filter((e) => e.status !== "OPEN");
  const running = hasRun && summary?.status !== "finished";

  const decide = async (e: Escalation, verb: Verb) => {
    if (!runId) return;
    setHandled((h) => ({ ...h, [e.escalation_id]: { busy: verb } }));
    try {
      const res = await api.decide(runId, e.escalation_id, verb, notes[e.escalation_id]?.trim() ?? "");
      setHandled((h) => ({ ...h, [e.escalation_id]: { message: res.message, failed: !res.ok } }));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Something went wrong.";
      setHandled((h) => ({ ...h, [e.escalation_id]: { message: msg, failed: true } }));
    }
    onChanged();
  };

  return (
    <section className="panel" aria-labelledby="queue-h">
      <div className="panel-head">
        <h2 id="queue-h">
          Waiting for you
          {open.length > 0 && <span className="count" aria-label={`${open.length} waiting`}>{open.length}</span>}
        </h2>
      </div>
      {open.length === 0 && closed.length === 0 && (
        <Empty>{!hasRun ? "Purchase orders over the approval limit and escalations land here." : running ? "Nothing yet." : "Nothing is waiting for you."}</Empty>
      )}
      {open.length > 0 && (
        <div className="queue">
          {open.map((e) => {
            const h = handled[e.escalation_id];
            const isApproval = e.kind === "APPROVAL";
            const canAnswer = hasRun && !running && (!isApproval || !!e.po_id);
            const ask = escalationAsk(e.kind);
            const [yes, no]: [Verb, Verb] = isApproval ? ["approve", "reject"] : ["accept", "decline"];
            return (
              <div className="queue-item" key={e.escalation_id}>
                <div>
                  <div className="queue-kind">{escalationKind(e.kind)} <span className="mono">{e.escalation_id}</span></div>
                  <p><WithIds text={e.summary} /></p>
                </div>
                <EscalationContext e={e} why={ask.why} />
                {canAnswer ? (
                  <>
                    <div className="queue-actions">
                      <input
                        className="queue-note"
                        type="text"
                        placeholder="Note (optional)"
                        aria-label={`Note for ${e.escalation_id}`}
                        value={notes[e.escalation_id] ?? ""}
                        disabled={!!h?.busy}
                        onChange={(ev) => setNotes((n) => ({ ...n, [e.escalation_id]: ev.target.value }))}
                      />
                      <span className="queue-buttons">
                        <button type="button" className="btn" disabled={!!h?.busy} aria-label={`${ask.yes} ${e.po_id ?? e.escalation_id}`} onClick={() => decide(e, yes)}>
                          {h?.busy === yes ? "Saving" : ask.yes}
                        </button>
                        <button type="button" className="btn neg" disabled={!!h?.busy} aria-label={`${ask.no} ${e.po_id ?? e.escalation_id}`} onClick={() => decide(e, no)}>
                          {h?.busy === no ? "Saving" : ask.no}
                        </button>
                      </span>
                    </div>
                    <p className="queue-done">{ask.hint}</p>
                  </>
                ) : (
                  <p className="queue-done">{isApproval ? "Approve or reject" : "Answer"} once the run finishes.</p>
                )}
                {h?.message && !h.busy && <p className={`queue-result ${h.failed ? "neg" : ""}`} role="status">{h.message}</p>}
              </div>
            );
          })}
        </div>
      )}
      {open.some((e) => e.kind !== "APPROVAL") && (
        <p className="queue-done" style={{ marginTop: 4 }}>Answering an escalation records your decision with your note. It does not re-run the agent, and the run's score stays the same.</p>
      )}
      {closed.length > 0 && (
        <div className="queue" style={open.length ? { borderTop: "1px solid var(--rule)", marginTop: 4 } : undefined}>
          {closed.map((e) => {
            const h = handled[e.escalation_id];
            return (
              <div className="queue-item" key={e.escalation_id} style={{ padding: "10px 0" }}>
                <p className="queue-done">
                  <span className="mono">{e.escalation_id}</span> {escalationKind(e.kind).toLowerCase()}, {humanize(e.status).toLowerCase()}
                  {e.answer_note && <>: <q>{e.answer_note}</q></>}
                </p>
                {h?.message && <p className={`queue-result ${h.failed ? "neg" : ""}`} role="status">{h.message}</p>}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* ---------- the context a person needs to answer an escalation ---------- */

const COUNT_KEY = /qty|quantity|units|cases|days|count|need|demand/i; // checked first: "budget_max_qty" is units
const MONEY_KEY = /cost|budget|value|price|spend|amount|dollars/i;

function factLabel(key: string): string {
  return humanize(key).replace(/\b(sku|po|id)\b/gi, (w) => w.toUpperCase());
}

function factValue(key: string, v: unknown): string {
  if (typeof v === "number") {
    return !COUNT_KEY.test(key) && MONEY_KEY.test(key) ? money(v) : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ");
  if (v && typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** "CODE: message" -> the parts; a finding without a code is all message. */
function splitFinding(f: string): { code: string | null; message: string } {
  const m = /^([A-Z][A-Z0-9_]+):\s*(.*)$/s.exec(f);
  return m ? { code: m[1], message: m[2] } : { code: null, message: f };
}

function EscalationContext({ e, why }: { e: Escalation; why: string }) {
  const details = e.details ?? {};
  const findings = Array.isArray(details.findings) ? details.findings.map(String) : [];
  const facts = Object.entries(details).filter(([k, v]) => {
    if (k === "findings" || v === null || v === "" || (Array.isArray(v) && v.length === 0)) return false;
    return !(e.kind === "VERIFICATION_FAILED" && k === "outcome" && v === "DECIDED"); // the normal case, says nothing
  });
  return (
    <div className="queue-context">
      <p className="queue-why">{why}</p>
      {findings.length > 0 && (
        <ul className="queue-findings" aria-label="Verifier findings">
          {findings.map((f, i) => {
            const { code, message } = splitFinding(f);
            return (
              <li key={i}>
                {code && <span className="mono">{humanize(code)}</span>}
                <span><WithIds text={message} /></span>
              </li>
            );
          })}
        </ul>
      )}
      {facts.length > 0 && (
        <dl className="facts">
          {facts.map(([k, v]) => (
            <div key={k}>
              <dt>{factLabel(k)}</dt>
              <dd><WithIds text={factValue(k, v)} /></dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
