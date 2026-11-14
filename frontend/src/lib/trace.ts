import type { ChatMessage, HarnessStep, ToolDef, TraceEvent } from "../types";
import { count, ordinal } from "./format";
import { humanize, type Tone } from "./words";

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

export type Actor = "harness" | "llm";

/** One model call, as a Langfuse-style generation: what was sent, what was offered, what came back. */
export interface Generation {
  n: number;
  model: string | null;
  delta: ChatMessage[]; // the messages added since the previous request
  context: ChatMessage[]; // every message sent so far, rebuilt from the deltas
  tools: ToolDef[];
  responded: boolean;
  text: string;
  toolCalls: { id: string; name: string; arguments: Record<string, unknown> }[];
  finishReason: string | null;
  tokensIn: number | null;
  tokensOut: number | null;
  latency: number | null;
}

/** How the run used the tools it was offered: calls the model made, and what the harness preloaded. */
export interface ToolUse {
  calls: Record<string, number>;
  preloaded: Set<string>;
}

/** depth: 0 for the run and each generation, 1 for what the model called, 2 for what the harness did about it. */
type Base = { key: string; actor: Actor; depth: 0 | 1 | 2 };
export type Item = Base &
  (
    | { kind: "started"; scenarioId: string; sku: string; trigger: Record<string, any> } // eslint-disable-line @typescript-eslint/no-explicit-any
    | { kind: "preload"; calls: Call[] }
    | { kind: "generation"; gen: Generation; use: ToolUse; finished: boolean }
    | { kind: "call"; call: Call }
    | { kind: "step"; step: HarnessStep; call: Call }
    | { kind: "exec"; call: Call }
    | { kind: "verification"; passed: boolean; round: number; findings: { code: string; message: string }[] }
    | { kind: "flagged"; message: string; findings: string[] }
    | { kind: "error"; message: string }
    | { kind: "note"; text: string }
    | { kind: "finished"; outcome: string; steps: number; latency: number; tokensIn: number; tokensOut: number }
  );

export function buildTimeline(events: TraceEvent[]): Item[] {
  const items: Item[] = [];
  const preload: Call[] = [];
  let preloadAdded = false;
  const pending: Call[] = [];
  const stepped = new Set<Call>(); // calls whose harness steps already say what happened
  const use: ToolUse = { calls: {}, preloaded: new Set() };
  const generations: Generation[] = [];
  let tools: ToolDef[] = [];
  const finished = events.some((e) => e.type === "run_finished");
  const h = (key: string, rest: object, depth: 0 | 2 = 0) => items.push({ key, actor: "harness", depth, ...rest } as Item);

  for (const e of events) {
    const d = e.data;
    switch (e.type) {
      case "run_started":
        h(`s${e.seq}`, { kind: "started", scenarioId: d.scenario_id, sku: d.sku, trigger: d.trigger ?? {} });
        break;
      case "tool_call": {
        const call: Call = { seq: e.seq, name: d.name, args: d.args ?? {}, by: d.by ?? "agent", callId: d.call_id };
        pending.push(call);
        if (call.by === "harness") {
          use.preloaded.add(call.name);
          if (!preloadAdded) {
            preloadAdded = true;
            h("preload", { kind: "preload", calls: preload });
          }
          preload.push(call);
        } else {
          use.calls[call.name] = (use.calls[call.name] ?? 0) + 1;
          items.push({ kind: "call", key: `c${e.seq}`, actor: "llm", depth: 1, call });
        }
        break;
      }
      case "harness_step": {
        const call = pending.find((c) => c.callId === d.call_id);
        if (!call) break;
        stepped.add(call);
        h(`h${e.seq}`, { kind: "step", step: d as HarnessStep, call }, 2);
        break;
      }
      case "tool_result": {
        const at = pending.findIndex((c) => (d.call_id ? c.callId === d.call_id : c.name === d.name));
        const call = at >= 0 ? pending.splice(at, 1)[0] : undefined;
        if (!call) break;
        call.result = d.result;
        call.ok = d.ok;
        const sentBack = call.name === "submit_decision" && (call.ok || String(d.result?.error ?? "").startsWith("Verification"));
        if (call.by !== "harness" && !stepped.has(call) && !sentBack) h(`x${e.seq}`, { kind: "exec", call }, 2);
        break;
      }
      case "llm_request": {
        const delta: ChatMessage[] = d.messages ?? [];
        if (d.tools) tools = d.tools;
        const prev = generations[generations.length - 1];
        const gen: Generation = {
          n: generations.length + 1, model: null, delta, context: [...(prev?.context ?? []), ...delta], tools,
          responded: false, text: "", toolCalls: [], finishReason: null, tokensIn: null, tokensOut: null, latency: null,
        };
        generations.push(gen);
        items.push({ kind: "generation", key: `g${e.seq}`, actor: "llm", depth: 0, gen, use, finished });
        break;
      }
      case "llm_response": {
        const gen = generations[generations.length - 1];
        if (!gen) break;
        gen.responded = true;
        gen.model = d.model ?? null;
        gen.text = typeof d.text === "string" ? d.text.trim() : "";
        gen.toolCalls = (d.tool_calls ?? []).map((c: any) => ({ id: c.id, name: c.name, arguments: c.arguments ?? {} })); // eslint-disable-line @typescript-eslint/no-explicit-any
        gen.finishReason = d.finish_reason ?? null;
        gen.tokensIn = d.usage?.input_tokens ?? null;
        gen.tokensOut = d.usage?.output_tokens ?? null;
        gen.latency = typeof d.latency_s === "number" ? d.latency_s : null;
        break;
      }
      case "recovered_tool_call":
        h(`n${e.seq}`, { kind: "note", text: `Recovered a ${d.name} call written in the model's text` });
        break;
      case "nudge":
        h(`n${e.seq}`, { kind: "note", text: `Reminded the agent to act or decide (reminder ${d.count})` });
        break;
      case "budget_locked": {
        const parts: string[] = Array.isArray(d.key) ? d.key : [];
        h(`n${e.seq}`, { kind: "note", text: `Retry limit reached for ${parts.slice(0, 2).join(" ") || "a write"}: further attempts are refused` });
        break;
      }
      case "verification":
        h(`v${e.seq}`, { kind: "verification", passed: !!d.passed, round: d.round ?? 1, findings: (d.findings ?? []).map((f: any) => ({ code: f.code, message: f.message })) }); // eslint-disable-line @typescript-eslint/no-explicit-any
        break;
      case "flagged":
        h(`f${e.seq}`, { kind: "flagged", message: d.message, findings: d.findings ?? [] });
        break;
      case "error":
        h(`e${e.seq}`, { kind: "error", message: d.message ?? "The run stopped with an error." });
        break;
      case "run_finished":
        h(`r${e.seq}`, { kind: "finished", outcome: d.outcome, steps: d.steps, latency: d.latency_s, tokensIn: d.tokens_in, tokensOut: d.tokens_out });
        break;
      default:
        break; // the decision is already visible as the submit_decision call
    }
  }
  return items;
}

const STAGES: Record<string, string> = { validator: "Validator", approval: "Approval", supplier: "Supplier" };

/** One harness step in words: its stage, a short status and its tone. */
export function stepView(s: HarnessStep): { label: string; text: string; tone: Tone } {
  const label = STAGES[s.stage] ?? humanize(s.stage);
  switch (s.status) {
    case "PASSED": return { label, text: "Passed", tone: "pos" };
    case "BLOCKED": return { label, text: "Blocked", tone: "neg" };
    case "NEEDS_JUSTIFICATION": return { label, text: "Needs a justification", tone: "warn" };
    case "AUTO_SUBMITTED": return { label, text: "Submitted automatically", tone: "pos" };
    case "PENDING_APPROVAL": return { label, text: "Waiting for approval", tone: "warn" };
    case "REJECTED": return { label, text: "Declined", tone: "neg" };
  }
  if (s.stage === "supplier" && typeof s.confirmed === "number" && typeof s.requested === "number")
    return { label, text: `Confirmed ${count(s.confirmed)} of ${count(s.requested)}`, tone: s.confirmed >= s.requested ? "pos" : "warn" };
  return { label, text: humanize(s.status), tone: "neutral" };
}

/** Where a tool belongs in the list the model was offered. */
export function toolGroup(name: string): "Read" | "Calculate" | "Write" | "Finish" {
  if (name.startsWith("get_")) return "Read";
  if (name === "plan_order") return "Calculate";
  return name === "submit_decision" ? "Finish" : "Write";
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

const stepsOf = (events: TraceEvent[], stage: string): HarnessStep[] =>
  events.filter((e) => e.type === "harness_step" && e.data.stage === stage).map((e) => e.data as HarnessStep);

export function loops(events: TraceEvent[], finished: boolean): [Loop, Loop, Loop] {
  const checks = stepsOf(events, "validator");

  // Validation: did the validator refuse anything, and did the agent get past it?
  let validation: Loop;
  if (checks.length === 0) {
    validation = { label: "Validation", text: finished ? "No purchase order written" : "Nothing written yet", tone: "idle" };
  } else {
    const blocked = checks.filter((c) => c.status === "BLOCKED").length;
    const unjustified = checks.filter((c) => c.status === "NEEDS_JUSTIFICATION").length;
    const passed = checks.filter((c) => c.status === "PASSED").length;
    const failures = blocked + unjustified;
    const lastFail = checks.map((c) => c.status !== "PASSED").lastIndexOf(true);
    const recovered = lastFail >= 0 && checks.slice(lastFail + 1).some((c) => c.status === "PASSED");
    const held = stepsOf(events, "approval").filter((a) => a.status === "PENDING_APPROVAL").length;
    if (failures === 0) {
      validation = {
        label: "Validation",
        text: held > 0 ? `${passed} passed, ${held} held for approval` : `${passed} passed, none blocked`,
        tone: held > 0 ? "warn" : "pos",
      };
    } else {
      const parts = [blocked ? `${blocked} blocked` : "", unjustified ? `${unjustified} needed a justification` : ""].filter(Boolean);
      validation = {
        label: "Validation",
        text: `${parts.join(", ")}, ${recovered ? "revised" : "not recovered"}`,
        tone: recovered ? "pos" : "neg",
      };
    }
  }

  // Supplier: did the supplier confirm what was asked, and was a shortfall made up?
  const outcomes = stepsOf(events, "supplier").map((s) => ({ status: s.status, requested: s.requested ?? 0, confirmed: s.confirmed ?? 0 }));
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
  return Object.entries(args)
    .filter(([, v]) => v !== null && v !== undefined)
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
