import type { EvalReport, Scenario } from "../types";
import type { Async } from "../hooks/useAsync";
import { percent } from "../lib/format";
import { BASELINE_NOTES, checkLabel, GROUPS } from "../lib/words";
import { Empty, ErrorBlock } from "./States";

const CHECK_ORDER = ["decision", "information", "constraints", "action", "validation", "recovery"];

function sorted(reports: EvalReport[]): EvalReport[] {
  const rank = (r: EvalReport) => (r.kind === "baseline" ? 1 : 0);
  return [...reports].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

function reportKind(r: EvalReport): string {
  return r.kind === "baseline" ? "Baseline" : "Model";
}

function repeatsWords(r: EvalReport): string {
  return `${r.repeats} ${r.repeats === 1 ? "run" : "runs"} per scenario${r.temperature !== null && r.temperature !== undefined ? `, temperature ${r.temperature.toFixed(1)}` : ""}`;
}

/** How many of the expected scenarios a report covers, or null when it is complete. */
function partialNote(r: EvalReport, expected: number): string | null {
  const covered = new Set(r.cards.map((c) => c.scenario_id)).size;
  return covered < expected || r.cards.length < expected * r.repeats ? `partial: ${covered} of ${expected} scenarios` : null;
}

export function EvalView({ evalData, scenarios }: { evalData: Async<EvalReport[]>; scenarios: Scenario[] | null }) {
  const { data, error, loading, reload } = evalData;
  if (error && !data) {
    return (
      <div className="page">
        <header className="title-row">
          <div className="title-block">
            <h1>Eval</h1>
          </div>
        </header>
        <div style={{ marginTop: 24 }}>
          <ErrorBlock title="Couldn't load the eval results" onRetry={reload}>{error.message}</ErrorBlock>
        </div>
      </div>
    );
  }
  const reports = sorted(data ?? []);
  const checkNames = [...new Set([...CHECK_ORDER, ...reports.flatMap((r) => Object.keys(r.summary.per_check))])].filter((n) => reports.some((r) => n in r.summary.per_check));
  const totalScenarios = Math.max(scenarios?.length ?? 0, ...reports.map((r) => r.summary.scenarios));
  const partial = new Map(reports.map((r) => [r.name, partialNote(r, totalScenarios)]));
  const allComplete = [...partial.values()].every((v) => v === null);

  return (
    <div className="page">
      <header className="title-row">
        <div className="title-block">
          <h1>Eval</h1>
          <p className="situation">
            {loading && !data
              ? "Loading the saved results."
              : reports.length === 0
                ? "How each model and baseline scored across the scenarios."
                : `${reports.length} ${reports.length === 1 ? "report" : "reports"} ${allComplete ? `compared across ${totalScenarios} scenarios` : `of ${totalScenarios} scenarios, some only partly covered, so not every pair is a full comparison`}. Every score is a deterministic check on the final database and the tool calls.`}
          </p>
        </div>
      </header>

      {!loading && data && reports.length === 0 ? (
        <div style={{ marginTop: 24 }}>
          <Empty left>No eval results yet. Run python -m app.evaluate in the backend folder and the reports appear here.</Empty>
        </div>
      ) : (
        <>
          <section className="eval-section" style={{ marginTop: 24 }} aria-labelledby="cmp-h">
            <div className="section-head">
              <h2 id="cmp-h">Comparison</h2>
              <p className="meta">Passed out of applicable, per check</p>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Report</th>
                    <th scope="col" className="n">Scenarios passed</th>
                    <th scope="col" className="n">Runs passed</th>
                    {checkNames.map((c) => (
                      <th key={c} scope="col" className="n">{checkLabel(c)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r) => (
                    <tr key={r.name}>
                      <td>
                        <span className="report-name">{r.name}</span>
                        {partial.get(r.name) && <span className="sub">{partial.get(r.name)}</span>}
                        <span className="sub">{reportKind(r)}, {repeatsWords(r)}</span>
                      </td>
                      <td className="n num">
                        <strong style={{ fontWeight: 500 }}>{r.summary.scenarios_passed}</strong> of {r.summary.scenarios}
                      </td>
                      <td className="n num">
                        <strong style={{ fontWeight: 500 }}>{r.summary.runs_passed}</strong> of {r.summary.runs}
                        <span className="sub">{percent(r.summary.runs_passed, r.summary.runs)}</span>
                        <span className="bar" role="img" aria-label={`${r.summary.runs_passed} of ${r.summary.runs} runs passed`}>
                          <span style={{ width: `${r.summary.runs ? (r.summary.runs_passed / r.summary.runs) * 100 : 0}%` }} />
                        </span>
                      </td>
                      {checkNames.map((c) => {
                        const v = r.summary.per_check[c];
                        return (
                          <td key={c} className="n num">
                            {v && v[1] > 0 ? (
                              <>
                                {v[0]}/{v[1]}
                                <span className="sub">{percent(v[0], v[1])}</span>
                              </>
                            ) : (
                              <span className="muted">-</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="eval-grid">
            <section aria-labelledby="mx-h">
              <div className="section-head">
                <h2 id="mx-h">Per scenario</h2>
                <p className="meta">Runs passed out of runs</p>
              </div>
              <Matrix reports={reports} scenarios={scenarios} />
            </section>
            <aside className="panel" aria-label="How to read the matrix">
              <div className="panel-head">
                <h2>Reading the matrix</h2>
              </div>
              <div className="legend">
                <div><span className="score pos">3/3</span><span>Every run passed</span></div>
                <div><span className="score warn">1/3</span><span>Some runs passed</span></div>
                <div><span className="score neg">0/3</span><span>No run passed</span></div>
                <div><span className="score none">-</span><span>Not evaluated</span></div>
              </div>
              {reports.some((r) => r.kind === "baseline") && (
                <>
                  <h3 style={{ margin: "20px 0 8px", fontSize: 14, fontWeight: 600 }}>Baselines</h3>
                  <dl className="grid gap-3 m-0">
                    {reports.filter((r) => r.kind === "baseline").map((r) => (
                      <div key={r.name}>
                        <dt style={{ fontWeight: 500 }}>{r.name}</dt>
                        <dd className="muted">{BASELINE_NOTES[r.name] ?? "A fixed policy run for comparison, not a model."}</dd>
                      </div>
                    ))}
                  </dl>
                </>
              )}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}

function Matrix({ reports, scenarios }: { reports: EvalReport[]; scenarios: Scenario[] | null }) {
  // Rows come from the scenarios the API knows; a scenario no report touched still appears, as dashes.
  const known = scenarios ?? [];
  const ids = new Set(known.map((s) => s.id));
  const extra = [...new Set(reports.flatMap((r) => r.cards.map((c) => c.scenario_id)))].filter((id) => !ids.has(id));
  const rows = [...known.map((s) => ({ id: s.id, title: s.title, group: s.group })), ...extra.map((id) => ({ id, title: id, group: 0 }))];
  const groups = [...new Set(rows.map((r) => r.group))].sort();

  const cell = (r: EvalReport, id: string) => {
    const cards = r.cards.filter((c) => c.scenario_id === id);
    if (cards.length === 0) return <span className="score none" aria-label="not evaluated">-</span>;
    const k = cards.filter((c) => c.passed).length;
    const tone = k === cards.length ? "pos" : k === 0 ? "neg" : "warn";
    return <span className={`score ${tone}`}>{k}/{cards.length}</span>;
  };

  return (
    <div className="table-wrap">
      <table className="matrix">
        <thead>
          <tr>
            <th scope="col">Scenario</th>
            {reports.map((r) => (
              <th key={r.name} scope="col" className="cell">
                <span className="name">{r.name}</span>
                <span className="sub">{reportKind(r)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <GroupRows key={g} group={g} rows={rows.filter((r) => r.group === g)} reports={reports} cell={cell} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({ group, rows, reports, cell }: { group: number; rows: { id: string; title: string }[]; reports: EvalReport[]; cell: (r: EvalReport, id: string) => React.ReactNode }) {
  return (
    <>
      <tr className="group-row">
        <td colSpan={reports.length + 1}>
          {group ? `${group} ${GROUPS[group] ?? ""}` : "Other"}
        </td>
      </tr>
      {rows.map((row) => (
        <tr key={row.id}>
          <td style={{ maxWidth: 360 }}>
            {row.title}
            <span className="sub mono">{row.id}</span>
          </td>
          {reports.map((r) => (
            <td key={r.name} className="cell">{cell(r, row.id)}</td>
          ))}
        </tr>
      ))}
    </>
  );
}
