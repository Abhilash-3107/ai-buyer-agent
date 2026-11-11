import type { Escalation, RunSummary, Scenario, TraceEvent } from "../types";
import { count, plural } from "./format";
import { decisionWord, escalationKind, outcomeMessage } from "./words";

export const openApprovals = (s: RunSummary | null): Escalation[] =>
  (s?.escalations ?? []).filter((e) => e.kind === "APPROVAL" && e.status === "OPEN");

export const otherOpen = (s: RunSummary | null): Escalation[] =>
  (s?.escalations ?? []).filter((e) => e.kind !== "APPROVAL" && e.status === "OPEN");

export const bandWords = ([lo, hi]: [number, number]) => (lo === hi ? (lo === 0 ? "nothing" : `${count(lo)} units`) : `${count(lo)} to ${count(hi)} units`);

export function expectedLine(sc: Scenario): string {
  const e = sc.expected;
  const call = decisionWord(e.decision);
  const buy = e.new_buy_qty[1] === 0 ? "buy nothing" : `buy ${bandWords(e.new_buy_qty)}`;
  const esc = e.escalation ? `, escalate for ${escalationKind(e.escalation).toLowerCase()}` : "";
  return `The expected call is ${call}: ${buy}${esc}.`;
}

export interface Finding {
  verdict: string;
  tone: "pos" | "neg" | "warn" | "neutral";
  text: string;
  more: { tone: "pos" | "neg" | "warn" | ""; text: string }[];
  /** A short label for assistive technology when the state changes. */
  live: string;
}

export function finding(
  scenario: Scenario,
  summary: RunSummary | null,
  events: TraceEvent[],
  hasRun: boolean,
): Finding {
  if (!hasRun) {
    return { verdict: "No run yet.", tone: "neutral", text: expectedLine(scenario), more: [], live: "No run yet" };
  }
  const running = !summary || summary.status === "running";
  if (running) {
    const turn = events.reduce((m, e) => Math.max(m, e.turn), 0);
    const calls = events.filter((e) => e.type === "tool_call" && e.data.by !== "system").length;
    return {
      verdict: "Running.",
      tone: "warn",
      text:
        events.length === 0
          ? "Starting up."
          : turn === 0
            ? "Loading the situation for the agent."
            : `Turn ${turn}, ${plural(calls, "tool call")} so far.`,
      more: [],
      live: "Run in progress",
    };
  }
  const errorEvent = [...events].reverse().find((e) => e.type === "error");
  if (summary.outcome !== "DECIDED") {
    const why = outcomeMessage(summary.outcome ?? "INTERRUPTED");
    const interrupted = (summary.outcome ?? "INTERRUPTED") === "INTERRUPTED";
    return {
      verdict: "Run failed.",
      tone: "neg",
      text: errorEvent ? (interrupted ? `The run stopped with an error: ${errorEvent.data.message}` : `${why} ${errorEvent.data.message}`) : why,
      more: otherQueue(summary),
      live: "Run failed",
    };
  }
  const card = summary.scorecard;
  const decided = decisionWord(summary.decision?.decision);
  const more: Finding["more"] = [];
  if (summary.verification) {
    const v = summary.verification;
    if (v.passed) more.push({ tone: "pos", text: "Verifier passed" });
    else {
      const extra = v.findings.length > 1 ? ` (${v.findings.length - 1} more)` : "";
      more.push({ tone: "neg", text: `Verifier failed: ${v.findings[0]?.message ?? "no reason given"}${extra}` });
    }
  }
  more.push(...otherQueue(summary));

  if (!card) {
    return { verdict: `Decided ${decided}.`, tone: "neutral", text: "Scoring is not available for this run.", more, live: "Run finished" };
  }
  const applicable = card.checks.filter((c) => c.applicable);
  const passedN = applicable.filter((c) => c.passed).length;
  const failed = applicable.filter((c) => !c.passed).map((c) => c.name);
  const decisionOk = card.checks.find((c) => c.name === "decision")?.passed ?? false;
  const bought = card.new_buy_units > 0 ? `bought ${count(card.new_buy_units)} units` : "bought nothing";
  if (card.passed) {
    return { verdict: "Right call.", tone: "pos", text: `The agent decided ${decided} and ${bought}. ${passedN} of ${applicable.length} checks passed.`, more, live: "Run finished, right call" };
  }
  if (decisionOk) {
    return { verdict: "Right decision, but checks failed.", tone: "warn", text: `The agent decided ${decided} as expected and ${bought}. Failed: ${failed.join(", ")}.`, more, live: "Run finished, some checks failed" };
  }
  return {
    verdict: "Wrong call.",
    tone: "neg",
    text: `The agent decided ${decided} where ${decisionWord(scenario.expected.decision)} was expected. ${passedN} of ${applicable.length} checks passed.`,
    more,
    live: "Run finished, wrong call",
  };
}

function otherQueue(s: RunSummary): Finding["more"] {
  const approvals = openApprovals(s);
  const others = otherOpen(s);
  const out: Finding["more"] = [];
  if (approvals.length) out.push({ tone: "warn", text: `${plural(approvals.length, "PO")} waiting for your approval` });
  if (others.length) out.push({ tone: "warn", text: `${plural(others.length, "escalation")} open: ${[...new Set(others.map((o) => escalationKind(o.kind).toLowerCase()))].join(", ")}` });
  if (!approvals.length && !others.length) out.push({ tone: "", text: "Nothing waiting for you" });
  return out;
}
