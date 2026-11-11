import type { TraceEvent, WriteResult } from "../types";
import { count, ordinal } from "./format";
import type { Tone } from "./words";

/* The trace as the page shows it. Everything here is derived from the event list (plan section 11):
   no business logic, only grouping and wording. */

export const WRITE_STATUSES = ["WRITTEN", "BLOCKED", "NEEDS_JUSTIFICATION", "PENDING_APPROVAL", "NOT_ALLOWED"];

export interface Call {
  seq: number;
  name: string;
  args: Record<string, unknown>;
  by: string;
  callId?: string;
  result?: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  ok?: boolean;
}

export type Item =
  | { kind: "preload"; key: string; calls: Call[] }
  | { kind: "turn"; key: string; turn: number; latency: number | null }
  | { kind: "text"; key: string; text: string }
  | { kind: "call"; key: string; call: Call }
  | { kind: "decision"; key: string; data: Record<string, any>; revised: boolean } // eslint-disable-line @typescript-eslint/no-explicit-any
  | { kind: "verification"; key: string; passed: boolean; round: number; findings: { code: string; message: string }[] }
  | { kind: "flagged"; key: string; message: string; findings: string[] }
  | { kind: "error"; key: string; message: string }
  | { kind: "note"; key: string; text: string }
  | { kind: "finished"; key: string; outcome: string; steps: number; latency: number; tokensIn: number; tokensOut: number };

export function buildTimeline(events: TraceEvent[]): Item[] {
  const items: Item[] = [];
  const preload: Call[] = [];
  let preloadIndex = -1;
  const pending: Call[] = [];
  let decisions = 0;

  for (const e of events) {
    const d = e.data;
    switch (e.type) {
      case "tool_call": {
        const call: Call = { seq: e.seq, name: d.name, args: d.args ?? {}, by: d.by ?? "agent", callId: d.call_id };
        pending.push(call);
        if (call.by === "system") {
          if (preloadIndex === -1) {
            preloadIndex = items.length;
            items.push({ kind: "preload", key: `preload`, calls: preload });
          }
          preload.push(call);
        } else {
          items.push({ kind: "call", key: `c${e.seq}`, call });
        }
        break;
      }
      case "tool_result": {
        const at = pending.findIndex((c) => (d.call_id ? c.callId === d.call_id : c.name === d.name));
        const call = at >= 0 ? pending.splice(at, 1)[0] : undefined;
        if (call) {
          call.result = d.result;
          call.ok = d.ok;
        }
        break;
      }
      case "llm_response": {
        items.push({ kind: "turn", key: `t${e.seq}`, turn: e.turn, latency: typeof d.latency_s === "number" ? d.latency_s : null });
        if (typeof d.text === "string" && d.text.trim()) items.push({ kind: "text", key: `x${e.seq}`, text: d.text.trim() });
        break;
      }
      case "recovered_tool_call":
        items.push({ kind: "note", key: `n${e.seq}`, text: `Recovered a ${d.name} call written in the model's text` });
        break;
      case "nudge":
        items.push({ kind: "note", key: `n${e.seq}`, text: `Reminded the agent to act or decide (reminder ${d.count})` });
        break;
      case "budget_locked": {
        const parts: string[] = Array.isArray(d.key) ? d.key : [];
        items.push({ kind: "note", key: `n${e.seq}`, text: `Retry limit reached for ${parts.slice(0, 2).join(" ") || "a write"}: further attempts are refused` });
        break;
      }
      case "decision":
        items.push({ kind: "decision", key: `d${e.seq}`, data: d, revised: decisions++ > 0 });
        break;
      case "verification":
        items.push({ kind: "verification", key: `v${e.seq}`, passed: !!d.passed, round: d.round ?? 1, findings: (d.findings ?? []).map((f: any) => ({ code: f.code, message: f.message })) }); // eslint-disable-line @typescript-eslint/no-explicit-any
        break;
      case "flagged":
        items.push({ kind: "flagged", key: `f${e.seq}`, message: d.message, findings: d.findings ?? [] });
        break;
      case "error":
        items.push({ kind: "error", key: `e${e.seq}`, message: d.message ?? "The run stopped with an error." });
        break;
      case "run_finished":
        items.push({ kind: "finished", key: `r${e.seq}`, outcome: d.outcome, steps: d.steps, latency: d.latency_s, tokensIn: d.tokens_in, tokensOut: d.tokens_out });
        break;
      default:
        break; // run_started and unknown types add nothing a buyer needs
    }
  }
  return items;
}

/** The write status of a tool result, when it is one of the write pipeline's answers. */
export function writeStatus(result: Record<string, any> | undefined): string | undefined { // eslint-disable-line @typescript-eslint/no-explicit-any
  const s = result?.status;
  return typeof s === "string" && WRITE_STATUSES.includes(s) ? s : undefined;
}

export function writeTone(status: string): Tone {
  switch (status) {
    case "WRITTEN": return "pos";
    case "BLOCKED":
    case "NOT_ALLOWED": return "neg";
    default: return "warn";
  }
}

/* ---------- the loop strip ---------- */

export interface Loop {
  label: string;
  text: string;
  tone: Tone | "idle";
}

interface AgentWrite {
  status: string;
  result: WriteResult;
}

function agentWrites(events: TraceEvent[]): AgentWrite[] {
  const out: AgentWrite[] = [];
  for (const e of events) {
    if (e.type !== "tool_result" || e.data.by === "system") continue;
    const status = writeStatus(e.data.result);
    if (status) out.push({ status, result: e.data.result as WriteResult });
  }
  return out;
}

export function loops(events: TraceEvent[], finished: boolean): [Loop, Loop, Loop] {
  const writes = agentWrites(events);

  // Validation: did the write pipeline refuse anything, and did the agent get past it?
  let validation: Loop;
  if (writes.length === 0) {
    validation = { label: "Validation", text: finished ? "No purchase order written" : "Nothing written yet", tone: "idle" };
  } else {
    const blocked = writes.filter((w) => w.status === "BLOCKED").length;
    const unjustified = writes.filter((w) => w.status === "NEEDS_JUSTIFICATION").length;
    const refused = writes.filter((w) => w.status === "NOT_ALLOWED").length;
    const failures = blocked + unjustified + refused;
    const lastFail = writes.map((w) => ["BLOCKED", "NEEDS_JUSTIFICATION", "NOT_ALLOWED"].includes(w.status)).lastIndexOf(true);
    const recovered = lastFail >= 0 && writes.slice(lastFail + 1).some((w) => w.status === "WRITTEN" || w.status === "PENDING_APPROVAL");
    const held = writes.filter((w) => w.status === "PENDING_APPROVAL").length;
    if (failures === 0) {
      const written = writes.length;
      validation = {
        label: "Validation",
        text: held > 0 ? `${written} written, ${held} held for approval` : `${written} written, none blocked`,
        tone: held > 0 ? "warn" : "pos",
      };
    } else {
      const parts = [
        blocked ? `${blocked} blocked` : "",
        unjustified ? `${unjustified} needed a justification` : "",
        refused ? `${refused} not allowed` : "",
      ].filter(Boolean);
      validation = {
        label: "Validation",
        text: `${parts.join(", ")}, ${recovered ? "revised" : "not recovered"}`,
        tone: recovered ? "pos" : "neg",
      };
    }
  }

  // Supplier: did the supplier confirm what was asked, and was a shortfall made up?
  const outcomes = writes.map((w) => w.result.supplier).filter((s): s is NonNullable<WriteResult["supplier"]> => !!s);
  let supplier: Loop;
  if (outcomes.length === 0) {
    supplier = { label: "Supplier", text: finished ? "Not contacted" : "Not contacted yet", tone: "idle" };
  } else {
    const firstShort = outcomes.findIndex((s) => s.confirmed < s.requested);
    if (firstShort === -1) {
      const last = outcomes[outcomes.length - 1];
      supplier = { label: "Supplier", text: `Confirmed ${count(last.confirmed)} of ${count(last.requested)}`, tone: "pos" };
    } else {
      const s = outcomes[firstShort];
      const later = outcomes.slice(firstShort + 1);
      const toppedUp = later.some((o) => o.confirmed >= o.requested && o.confirmed > 0);
      const rejected = s.status === "REJECTED" || s.confirmed === 0;
      const verb = rejected ? "Declined" : `Confirmed ${count(s.confirmed)} of ${count(s.requested)}`;
      supplier = {
        label: "Supplier",
        text: `${verb}${later.length ? (toppedUp ? ", topped up" : ", top-up also short") : ""}`,
        tone: toppedUp ? "pos" : rejected ? "neg" : "warn",
      };
    }
  }

  // Verifier: did the independent check pass, and on which try?
  const rounds = events.filter((e) => e.type === "verification");
  const flagged = events.some((e) => e.type === "flagged");
  let verifier: Loop;
  if (rounds.length === 0) {
    verifier = { label: "Verifier", text: finished ? "Did not run" : "Waiting for a decision", tone: "idle" };
  } else {
    const last = rounds[rounds.length - 1].data;
    const round = last.round ?? rounds.length;
    if (last.passed) {
      verifier = { label: "Verifier", text: round === 1 ? "Passed first time" : `Passed on ${ordinal(round)} try`, tone: "pos" };
    } else if (!finished && !flagged) {
      verifier = { label: "Verifier", text: `Found a problem on try ${round}, agent revising`, tone: "warn" };
    } else {
      verifier = { label: "Verifier", text: `Failed after ${round} ${round === 1 ? "try" : "tries"}${flagged ? ", flagged for a human" : ""}`, tone: "neg" };
    }
  }
  return [validation, supplier, verifier];
}

export function argEntries(args: Record<string, unknown>): { key: string; value: string }[] {
  const skip = new Set(["reason", "justification", "details", "summary", "note", "key_factors", "actions_taken"]);
  return Object.entries(args)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== undefined)
    .map(([key, v]) => ({
      key,
      value: Array.isArray(v) ? `${v.length} items` : typeof v === "object" ? "{...}" : String(v),
    }));
}

export const isId = (value: string) => /^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$/.test(value) || /^\d{8}T\d{6}-/.test(value);

/** One short phrase for what a tool returned. */
export function resultSummary(call: Call): { text: string; tone: Tone } {
  const r = call.result;
  if (!r) return { text: "Running", tone: "neutral" };
  const status = writeStatus(r);
  if (status) {
    const sup = r.supplier;
    if (sup) {
      const text = sup.status === "REJECTED" ? "Supplier declined" : `Supplier confirmed ${sup.confirmed} of ${sup.requested}`;
      return { text, tone: sup.confirmed >= sup.requested ? "pos" : sup.status === "REJECTED" ? "neg" : "warn" };
    }
    switch (status) {
      case "WRITTEN": return { text: "Written", tone: "pos" };
      case "BLOCKED": return { text: "Blocked", tone: "neg" };
      case "NEEDS_JUSTIFICATION": return { text: "Needs a justification", tone: "warn" };
      case "PENDING_APPROVAL": return { text: "Waiting for your approval", tone: "warn" };
      default: return { text: "Not allowed", tone: "neg" };
    }
  }
  if (call.name === "submit_decision" && call.ok === false && typeof r.error === "string" && r.error.startsWith("Verification"))
    return { text: "Sent back by the verifier", tone: "warn" };
  if (call.ok === false || r.ok === false) return { text: "Failed", tone: "neg" };
  if (call.name === "submit_decision") return { text: "Accepted", tone: "neutral" };
  const n = (v: unknown) => (Array.isArray(v) ? v.length : 0);
  switch (call.name) {
    case "get_inventory": return { text: `${r.on_hand} on hand`, tone: "neutral" };
    case "get_recommendation": return { text: `Recommends ${r.recommended_qty} units`, tone: "neutral" };
    case "get_purchase_orders": return { text: `${n(r.open_pos)} open`, tone: "neutral" };
    case "get_suppliers": return { text: `${n(r.suppliers)} suppliers`, tone: "neutral" };
    case "get_forecast": return { text: `${n(r.daily_forecast)} days`, tone: "neutral" };
    case "get_sales_history": return { text: `${n(r.daily_sales)} days`, tone: "neutral" };
    default: return { text: "Read", tone: "neutral" };
  }
}
