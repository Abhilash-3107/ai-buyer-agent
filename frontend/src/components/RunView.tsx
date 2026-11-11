import { useMemo } from "react";
import type { Health, RunListItem, Scenario } from "../types";
import { useRun } from "../hooks/useRun";
import { finding } from "../lib/derive";
import { stamp } from "../lib/format";
import { loops } from "../lib/trace";
import { decisionWord, GROUPS, TRIGGERS } from "../lib/words";
import { FindingLine, LoopStrip } from "./Finding";
import { Outcome } from "./Outcome";
import { Trace } from "./Trace";
import { ErrorBlock } from "./States";

interface Props {
  scenario: Scenario;
  runs: RunListItem[];
  runId: string | null;
  health: Health | null;
  starting: boolean;
  startError: string | null;
  onRun: () => void;
  onPick: (runId: string) => void;
  onSettled: () => void;
}

function runLabel(r: RunListItem): string {
  const verdict = r.status === "running" ? "running" : r.outcome !== "DECIDED" ? "failed to finish" : r.passed ? "matched" : "missed";
  return `${stamp(r.started_at)}, ${r.decision ? decisionWord(r.decision) : "no decision"}, ${verdict}`;
}

export function RunView({ scenario, runs, runId, health, starting, startError, onRun, onPick, onSettled }: Props) {
  const mine = runs.filter((r) => r.scenario_id === scenario.id);
  const state = useRun(runId, onSettled);
  const { events, summary, connection, error } = state;
  const hasRun = runId !== null;
  const running = hasRun && (summary?.status !== "finished") && !error;
  const finished = summary?.status === "finished";
  const sku = (events.find((e) => e.type === "run_started")?.data.sku as string | undefined) ?? null;

  const f = useMemo(() => finding(scenario, summary, events, hasRun), [scenario, summary, events, hasRun]);
  const strip = useMemo(() => {
    const l = loops(events, finished);
    return hasRun ? l : (l.map((x) => ({ ...x, text: "Not run yet", tone: "idle" as const })) as typeof l);
  }, [events, finished, hasRun]);

  const busy = starting || running;
  const modelNote = summary && health?.demo ? `Model: ${summary.model}` : null;

  return (
    <div className="page">
      <header className="title-row">
        <div className="title-block">
          <h1>{scenario.title}</h1>
          <p className="situation">{scenario.situation}</p>
          <p className="meta">
            <span className="mono">{scenario.id}</span>
            {" · "}
            {GROUPS[scenario.group]}
            {" · "}
            {TRIGGERS[scenario.trigger_type] ?? scenario.trigger_type}
            {modelNote ? ` · ${modelNote}` : ""}
          </p>
        </div>
        <div className="actions">
          {mine.length > 0 && (
            <select className="select" aria-label="Run history" value={runId ?? ""} onChange={(e) => e.target.value && onPick(e.target.value)}>
              {runId === null && <option value="">Run history</option>}
              {runId !== null && !mine.some((r) => r.run_id === runId) && <option value={runId}>This run</option>}
              {mine.map((r, i) => (
                <option key={r.run_id} value={r.run_id}>
                  {i === 0 ? "Latest: " : ""}
                  {runLabel(r)}
                </option>
              ))}
            </select>
          )}
          <button type="button" className="btn primary" onClick={onRun} disabled={busy} aria-busy={busy}>
            {busy ? "Running" : hasRun ? "Run again" : "Run"}
          </button>
        </div>
      </header>

      {startError && (
        <div style={{ marginTop: 16 }}>
          <ErrorBlock title="The run could not start" onRetry={onRun}>{startError}</ErrorBlock>
        </div>
      )}

      {error && hasRun ? (
        <div style={{ marginTop: 24 }}>
          <ErrorBlock title={error.status === 404 ? "This run was not found" : "Could not load this run"} onRetry={error.status === 404 ? undefined : state.refresh}>
            {error.status === 404 ? "It may have been cleared when the server restarted. Pick another run or start a new one." : error.message}
          </ErrorBlock>
        </div>
      ) : (
        <>
          <FindingLine finding={f} />
          <LoopStrip loops={strip} />
          <div className="body-grid">
            <Trace hasRun={hasRun} events={events} summary={summary} connection={connection} onReconnect={state.reconnect} />
            <Outcome scenario={scenario} summary={summary} hasRun={hasRun} runId={runId} sku={sku} onChanged={state.refresh} />
          </div>
        </>
      )}
    </div>
  );
}
