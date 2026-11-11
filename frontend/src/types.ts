// Shapes of the API in plan section 9 and the trace events in section 11.

export interface Health {
  ok: boolean;
  model: string;
  local: boolean;
  demo: boolean;
}

export interface Scenario {
  id: string;
  group: number;
  title: string;
  situation: string;
  trigger_type: string;
  expected: {
    decision: string;
    new_buy_qty: [number, number];
    allowed_suppliers: string[] | null;
    escalation: string | null;
    worked_example: string;
  };
}

export interface RunListItem {
  run_id: string;
  scenario_id: string;
  status: "running" | "finished";
  outcome: string | null;
  decision: string | null;
  passed: boolean | null;
  started_at: string;
}

export interface Decision {
  decision: string;
  new_units: number;
  daily_demand_used: number | null;
  key_factors: string[];
  actions_taken: string[];
  confidence: string;
  summary: string;
}

export interface Finding {
  code: string;
  message: string;
}

export interface Check {
  name: string;
  applicable: boolean;
  passed: boolean;
  reason: string;
}

export interface PurchaseOrder {
  po_id: string;
  supplier_id: string;
  supplier_name: string;
  status: string;
  qty_ordered: number;
  qty_confirmed: number | null;
  unit_cost: number;
  value: number;
  expected_arrival: string;
  created_by: string;
  parent_po_id: string | null;
}

export interface Escalation {
  escalation_id: string;
  kind: string;
  po_id: string | null;
  summary: string;
  status: string;
  created_at: string;
}

export interface RunSummary {
  run_id: string;
  scenario_id: string;
  status: "running" | "finished";
  model: string;
  outcome: string | null;
  decision: Decision | null;
  verification: { passed: boolean; findings: Finding[] } | null;
  scorecard: {
    passed: boolean;
    checks: Check[];
    new_buy_units: number;
    info_read_by_agent: string[];
  } | null;
  purchase_orders: PurchaseOrder[];
  escalations: Escalation[];
  totals: { turns: number; tokens_in: number; tokens_out: number; latency_s: number };
}

export interface SupplierOutcome {
  po_id: string;
  requested: number;
  confirmed: number;
  status: string;
  message: string;
  shortfall?: number;
}

export interface Violation {
  code: string;
  severity: "error" | "warning";
  message: string;
  details?: unknown;
}

export interface WriteResult {
  ok: boolean;
  status?: string;
  po_id?: string | null;
  escalation_id?: string | null;
  message?: string;
  violations?: Violation[];
  shortfall?: number | null;
  supplier?: SupplierOutcome | null;
  error?: string;
  writes_locked?: boolean;
}

export interface TraceEvent {
  seq: number;
  turn: number;
  type: string;
  // The payload differs per event type; readers narrow what they need.
  data: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  ts: number;
}

export interface EvalCheckCard {
  name: string;
  applicable: boolean;
  passed: boolean;
  reason: string;
}

export interface EvalCard {
  scenario_id: string;
  run_id: string;
  model: string;
  checks: EvalCheckCard[];
  passed: boolean;
  outcome: string;
  decision: string | null;
}

export interface EvalReport {
  name: string;
  kind: "model" | "baseline" | string;
  repeats: number;
  temperature: number | null;
  summary: {
    scenarios_passed: number;
    scenarios: number;
    runs_passed: number;
    runs: number;
    per_check: Record<string, [number, number]>;
  };
  cards: EvalCard[];
}

export interface ApprovalResult {
  ok: boolean;
  status: string;
  message: string;
  po_id: string | null;
  supplier: SupplierOutcome | null;
}
