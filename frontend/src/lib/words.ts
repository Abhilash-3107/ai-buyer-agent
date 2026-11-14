// The words of the trade: the API's codes translated for a buyer. Display only, no logic.

export type Tone = "pos" | "neg" | "warn" | "neutral";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
export const humanize = (code: string) => cap(code.replaceAll("_", " "));

export const GROUPS: Record<number, string> = {
  1: "Recommendation review",
  2: "Supplier can't fulfil",
  3: "Demand changed",
  4: "Purchasing constraint",
};

export const decisionWord = (d: string | null | undefined) => (d ? humanize(d) : "-");

export const TRIGGERS: Record<string, string> = {
  RECOMMENDATION_REVIEW: "Triggered by a recommendation to review",
  SUPPLIER_EVENT: "Triggered by a supplier event",
  DEMAND_ALERT: "Triggered by a demand alert",
};

export function poStatus(status: string): { label: string; tone: Tone } {
  switch (status) {
    case "PENDING_APPROVAL": return { label: "Waiting for approval", tone: "warn" };
    case "SUBMITTED": return { label: "Sent to supplier", tone: "neutral" };
    case "CONFIRMED": return { label: "Confirmed", tone: "pos" };
    case "PARTIALLY_CONFIRMED": return { label: "Part confirmed", tone: "warn" };
    case "REJECTED": return { label: "Supplier declined", tone: "neg" };
    case "CANCELLED": return { label: "Cancelled", tone: "neutral" };
    case "RECEIVED": return { label: "Received", tone: "pos" };
    default: return { label: humanize(status), tone: "neutral" };
  }
}

export function creatorWord(by: string): string {
  if (by === "agent") return "raised by the agent";
  if (by === "human") return "raised by you";
  return "already open";
}

export function escalationKind(kind: string): string {
  switch (kind) {
    case "APPROVAL": return "Approval";
    case "BUDGET_INCREASE": return "Budget increase";
    case "INVESTIGATION": return "Investigation";
    case "VERIFICATION_FAILED": return "Verification failed";
    default: return humanize(kind);
  }
}

/** What an escalation is asking for, and the yes/no labels and their meaning for answering one. */
export function escalationAsk(kind: string): { why: string; yes: string; no: string; hint: string } {
  switch (kind) {
    case "APPROVAL": return {
      why: "This PO is over the approval limit, so it is held and the supplier has not been contacted.",
      yes: "Approve", no: "Reject",
      hint: "Approve sends the PO to the supplier. Reject cancels it.",
    };
    case "BUDGET_INCREASE": return {
      why: "The agent says the category budget is too small for what it thinks is needed, and asks for more.",
      yes: "Approve increase", no: "Decline",
      hint: "Approve if the extra spend is justified, decline if the shortfall should stand. Either way the budget and the POs stay as they are; this records your call.",
    };
    case "VERIFICATION_FAILED": return {
      why: "After the run, the verifier checked the agent's final answer against the database and found problems nobody fixed.",
      yes: "Resolved", no: "Dismiss",
      hint: "Mark resolved if the finding is right and you have dealt with it, dismiss if the verifier got it wrong.",
    };
    case "INVESTIGATION": return {
      why: "The agent says the data cannot support a decision and asks a person to look into it.",
      yes: "Resolved", no: "Dismiss",
      hint: "Mark resolved once the data has been looked into, dismiss if there is nothing to investigate.",
    };
    case "SUPPLIER_ISSUE": return {
      why: "The agent hit a problem with a supplier it cannot fix itself.",
      yes: "Resolved", no: "Dismiss",
      hint: "Mark resolved once the supplier problem is handled, dismiss if it is not a real problem.",
    };
    default: return {
      why: "The agent asks a person to decide.",
      yes: "Accept", no: "Decline",
      hint: "Your answer is recorded with your note.",
    };
  }
}

export function outcomeMessage(outcome: string): string {
  switch (outcome) {
    case "INTERRUPTED": return "The server stopped before this run finished.";
    case "CONTEXT_TRUNCATED": return "The model ran out of context before it could decide.";
    case "LLM_ERROR": return "The model could not be reached or returned an error.";
    case "MAX_STEPS": return "The agent used all of its steps without deciding.";
    default: return `The run ended without a decision (${humanize(outcome)}).`;
  }
}

export const CHECK_LABELS: Record<string, string> = {
  decision: "Decision",
  information: "Information",
  constraints: "Constraints",
  action: "Action",
  validation: "Validation",
  recovery: "Recovery",
};
export const checkLabel = (name: string) => CHECK_LABELS[name] ?? humanize(name);

export function demoLabel(model: string): string {
  const policy = model.replace(/^baseline:/, "").replaceAll("_", "-");
  return `Demo: ${policy} policy`;
}

export const BASELINE_NOTES: Record<string, string> = {
  rubber_stamp: "Does what the trigger implies without thinking, and always says accept.",
  do_nothing: "Never writes anything and rejects every trigger.",
};
