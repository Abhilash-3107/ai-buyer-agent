import type {
  ApprovalResult,
  EvalReport,
  Health,
  RunListItem,
  RunSummary,
  Scenario,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "The API did not answer.");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* the body was not JSON; keep the status line */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

/** approve/reject release or cancel a held PO; accept/decline answer any other escalation (records only). */
export type Verb = "approve" | "reject" | "accept" | "decline";

export const api = {
  health: () => request<Health>("/api/health"),
  scenarios: () => request<Scenario[]>("/api/scenarios"),
  runs: () => request<RunListItem[]>("/api/runs"),
  run: (id: string) => request<RunSummary>(`/api/runs/${encodeURIComponent(id)}`),
  eval: () => request<EvalReport[]>("/api/eval"),
  startRun: (scenarioId: string) =>
    request<{ run_id: string; scenario_id: string }>("/api/runs", post({ scenario_id: scenarioId })),
  decide: (runId: string, escalationId: string, verb: Verb, note = "") =>
    request<ApprovalResult>(
      `/api/runs/${encodeURIComponent(runId)}/escalations/${encodeURIComponent(escalationId)}/${verb}`,
      post({ note }),
    ),
};
