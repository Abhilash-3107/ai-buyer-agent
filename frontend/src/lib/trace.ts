import type { ChatMessage, HarnessStep, ToolDef, TraceEvent } from "../types";
import { count, ordinal, plural } from "./format";
import { decisionWord, humanize, type Tone } from "./words";

/* The trace as the page shows it. Everything here is derived from the event list (plan section 11):
   no business logic, only grouping and wording. */

export const WRITE_STATUSES = ["WRITTEN", "BLOCKED", "NEEDS_JUSTIFICATION", "PENDING_APPROVAL", "NOT_ALLOWED"];

export interface Call {
  name: string;
  args: Record<string, unknown>;
  by: string;
  callId?: string;
  result?: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  ok?: boolean;
}

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

export type NodeType = "agent" | "span" | "generation" | "tool" | "guardrail" | "event";

/** One node of the trace tree: the run, a model call, a tool run, or a harness check or event.
    Runs saved before phase 9 also have a "Preload context" span of reads the code did itself. */
export interface TraceNode {
  id: string; // derived from the event seq, so selection and expansion survive new events
  type: NodeType;
  name: string;
  summary?: { text: string; tone: Tone }; // the short result on the right of the row
  start: number; // seconds since the run started
  end: number | null; // null while it runs
  tokens?: { in: number; out: number };
  requestedBy?: string; // "LLM call 3" for a model's tool call, "Code" for a read the harness did in an old run
  recovered?: boolean; // the model wrote this call as text and the harness read it from there
  input?: unknown;
  output?: unknown;
  metadata?: Record<string, unknown>;
  detail?: string; // the harness's sentence for a check or event
  items?: { code?: string; message: string }[]; // violations or findings
  gen?: Generation;
  children: TraceNode[];
}

type Data = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const GATES = ["approval", "supplier"]; // steps that are something happening, not a check

export function buildTree(events: TraceEvent[], finished = events.some((e) => e.type === "run_finished")): TraceNode {
  const root: TraceNode = { id: "root", type: "agent", name: "Run", summary: { text: "Running", tone: "neutral" }, start: 0, end: null, children: [] };
  const generations: Generation[] = [];
  const genNodes: TraceNode[] = [];
  const pending: { call: Call; node: TraceNode }[] = [];
  const validators = new Map<string, TraceNode>(); // by tool node id: the violations arrive with the result
  const recovered = new Set<string>();
  let preload: TraceNode | undefined;
  let tools: ToolDef[] = [];
  let decision: Data | undefined;
  let end: Data | undefined;

  const note = (e: TraceEvent, node: Omit<TraceNode, "id" | "start" | "end" | "children" | "metadata">, parent: TraceNode) =>
    parent.children.push({ id: `n${e.seq}`, start: e.ts, end: e.ts, metadata: e.data, children: [], ...node });
  /** The tool run in progress, which is what a check or event during it belongs to. */
  const current = () => [...pending].reverse().find((p) => p.call.by === "agent")?.node;

  const openGeneration = (seq: number, ts: number, delta: ChatMessage[]) => {
    const prev = generations[generations.length - 1];
    const gen: Generation = {
      n: generations.length + 1, model: null, delta, context: [...(prev?.context ?? []), ...delta], tools,
      responded: false, text: "", toolCalls: [], finishReason: null, tokensIn: null, tokensOut: null, latency: null,
    };
    const node: TraceNode = {
      id: `g${seq}`, type: "generation", name: `LLM call ${gen.n}`, gen, start: ts, end: null, children: [],
      summary: finished ? { text: "No response", tone: "warn" } : { text: "Waiting for the model", tone: "neutral" },
    };
    generations.push(gen);
    genNodes.push(node);
    root.children.push(node);
  };

  for (const e of events) {
    const d = e.data;
    switch (e.type) {
      case "run_started":
        root.name = d.scenario_id ?? root.name;
        root.start = e.ts;
        root.input = { scenario_id: d.scenario_id, sku: d.sku, node_id: d.node_id, trigger: d.trigger ?? {} };
        break;
      case "tool_call": {
        const call: Call = { name: d.name, args: d.args ?? {}, by: d.by ?? "agent", callId: d.call_id };
        const node: TraceNode = { id: `t${e.seq}`, type: "tool", name: call.name, start: e.ts, end: null, input: call.args, metadata: { call_id: call.callId }, children: [] };
        node.summary = resultSummary(call);
        if (call.by === "agent") {
          const gen = genNodes[genNodes.length - 1];
          node.requestedBy = gen?.name;
          node.recovered = !!call.callId && recovered.has(call.callId);
          (gen ?? root).children.push(node);
        } else {
          node.requestedBy = "Code"; // only runs saved before phase 9 have harness reads
          if (!preload) {
            preload = { id: "preload", type: "span", name: "Preload context", requestedBy: "Code", start: e.ts, end: null, children: [] };
            root.children.push(preload);
          }
          preload.children.push(node);
          preload.summary = { text: plural(preload.children.length, "read"), tone: "neutral" };
        }
        pending.push({ call, node });
        break;
      }
      case "harness_step": {
        const step = d as HarnessStep;
        const parent = pending.find((p) => p.call.callId === d.call_id)?.node ?? current() ?? root;
        const v = stepView(step);
        const node: TraceNode = {
          id: `h${e.seq}`, type: GATES.includes(step.stage) ? "event" : "guardrail", name: v.label, summary: { text: v.text, tone: v.tone },
          detail: step.detail, start: e.ts, end: e.ts, metadata: d, children: [],
        };
        parent.children.push(node);
        if (step.stage === "validator") validators.set(parent.id, node);
        break;
      }
      case "tool_result": {
        const at = pending.findIndex((p) => (d.call_id ? p.call.callId === d.call_id : p.call.name === d.name));
        if (at < 0) break;
        const { call, node } = pending.splice(at, 1)[0];
        call.result = d.result;
        call.ok = d.ok;
        node.end = e.ts;
        node.output = d.result;
        node.summary = resultSummary(call);
        node.metadata = { call_id: call.callId, ok: d.ok, ...(node.recovered ? { recovered_from_text: true } : {}) };
        const violations: { code: string; severity: string; message: string }[] = call.result?.violations ?? [];
        const validator = validators.get(node.id);
        if (validator && violations.length > 0)
          validator.items = violations.map((x) => ({ code: x.code, message: `${x.severity === "warning" ? "Warning: " : ""}${x.message}` }));
        if (preload && call.by !== "agent") preload.end = e.ts;
        break;
      }
      case "llm_request":
        if (d.tools) tools = d.tools;
        openGeneration(e.seq, e.ts, d.messages ?? []);
        break;
      case "llm_response": {
        // An old run may hold a response without its request: it gets a generation of its own.
        if (genNodes.length === 0 || generations[generations.length - 1].responded) openGeneration(e.seq, Math.max(0, e.ts - (d.latency_s ?? 0)), []);
        const gen = generations[generations.length - 1];
        const node = genNodes[genNodes.length - 1];
        gen.responded = true;
        gen.model = d.model ?? null;
        gen.text = typeof d.text === "string" ? d.text.trim() : "";
        gen.toolCalls = (d.tool_calls ?? []).map((c: Data) => ({ id: c.id, name: c.name, arguments: c.arguments ?? {} }));
        gen.finishReason = d.finish_reason ?? null;
        gen.tokensIn = d.usage?.input_tokens ?? null;
        gen.tokensOut = d.usage?.output_tokens ?? null;
        gen.latency = typeof d.latency_s === "number" ? d.latency_s : null;
        node.end = e.ts;
        node.summary = gen.toolCalls.length === 0 ? { text: "Replied with text", tone: "neutral" } : undefined; // the tool runs below say what it asked for
        if (gen.tokensIn !== null) node.tokens = { in: gen.tokensIn, out: gen.tokensOut ?? 0 };
        node.metadata = { model: gen.model, finish_reason: gen.finishReason, input_tokens: gen.tokensIn, output_tokens: gen.tokensOut, latency_s: gen.latency };
        break;
      }
      case "recovered_tool_call": {
        if (d.call_id) recovered.add(d.call_id);
        const node = genNodes[genNodes.length - 1];
        if (node) node.summary = { text: `Wrote ${d.name} as text`, tone: "warn" };
        break;
      }
      case "nudge":
        note(e, { type: "event", name: "Reminder sent", summary: { text: `Reminder ${d.count}`, tone: "neutral" }, detail: "The model made no tool call, so the harness reminded it to act or decide." }, root);
        break;
      case "budget_locked": {
        const parts: string[] = Array.isArray(d.key) ? d.key : [];
        note(e, {
          type: "event", name: "Retry limit reached", summary: { text: "Writes locked", tone: "warn" },
          detail: `Too many failed attempts for ${parts.slice(0, 2).join(" ") || "a write"}: further attempts are refused.`,
        }, current() ?? root);
        break;
      }
      case "decision":
        decision = d;
        break;
      case "verification": {
        const findings: { code: string; message: string }[] = (d.findings ?? []).map((f: Data) => ({ code: f.code, message: f.message }));
        const round = d.round ?? 1;
        note(e, {
          type: "guardrail", name: "Verifier", items: findings,
          summary: d.passed ? { text: `Passed on try ${round}`, tone: "pos" } : { text: `Found ${plural(findings.length, "problem")} on try ${round}`, tone: "neg" },
        }, current() ?? root); // the one a submit_decision triggers sits under its tool run
        break;
      }
      case "flagged":
        note(e, { type: "event", name: "Flagged for a human", summary: { text: "Escalated", tone: "warn" }, detail: d.message, items: (d.findings ?? []).map((message: string) => ({ message })) }, root);
        break;
      case "error":
        note(e, { type: "event", name: "Error", summary: { text: "Run stopped", tone: "neg" }, detail: d.message ?? "The run stopped with an error." }, root);
        break;
      case "run_finished":
        end = { ...d, ts: e.ts };
        break;
      default:
        break;
    }
  }

  if (finished) for (const { node } of pending) node.summary = { text: "No result", tone: "warn" }; // a run that ended mid-tool
  const answered = generations.filter((g) => g.responded);
  const tokensIn = end?.tokens_in ?? answered.reduce((s, g) => s + (g.tokensIn ?? 0), 0);
  const tokensOut = end?.tokens_out ?? answered.reduce((s, g) => s + (g.tokensOut ?? 0), 0);
  if (tokensIn + tokensOut > 0) root.tokens = { in: tokensIn, out: tokensOut };
  root.end = end ? end.ts : null;
  root.output = end ? { outcome: end.outcome, decision: decision ?? null } : undefined;
  root.metadata = {
    model: answered[0]?.model ?? null, generations: generations.length, tokens_in: tokensIn, tokens_out: tokensOut,
    latency_s: end?.latency_s ?? null, verification_passed: end?.verification_passed ?? null,
  };
  if (end) {
    root.summary = end.outcome === "DECIDED" && decision
      ? { text: `${decisionWord(decision.decision)}, ${count(decision.new_units)} units`, tone: "neutral" }
      : { text: humanize(end.outcome), tone: "neg" };
  } else if (finished) {
    root.summary = { text: "Did not finish", tone: "neg" };
  }
  return root;
}

const STAGES: Record<string, string> = { request: "Request", validator: "Validator", approval: "Approval", supplier: "Supplier" };

/** One harness step in words: its stage, a short status and its tone. */
export function stepView(s: HarnessStep): { label: string; text: string; tone: Tone } {
  const label = STAGES[s.stage] ?? humanize(s.stage);
  if (s.stage === "request") {
    const tone: Tone = s.status === "ACCEPTED" ? "pos" : s.status === "REJECTED" ? "neg" : "warn";
    return { label, text: humanize(s.status), tone };
  }
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
    case "plan_order": return { text: `Suggests ${r.suggested_qty} units`, tone: "neutral" };
    case "get_purchase_orders": return { text: `${n(r.open_pos)} open`, tone: "neutral" };
    case "get_suppliers": return { text: `${n(r.suppliers)} suppliers`, tone: "neutral" };
    case "get_forecast": return { text: `${n(r.daily_forecast)} days`, tone: "neutral" };
    case "get_sales_history": return { text: `${n(r.daily_sales)} days`, tone: "neutral" };
    default: return { text: "Read", tone: "neutral" };
  }
}
