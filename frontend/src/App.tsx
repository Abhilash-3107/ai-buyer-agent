import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import { useAsync } from "./hooks/useAsync";
import { useRoute } from "./hooks/useRoute";
import { EvalView } from "./components/EvalView";
import { RunView } from "./components/RunView";
import { Sidebar, TopBar } from "./components/Shell";
import { ErrorBlock, PageSkeleton } from "./components/States";

export function App() {
  const [route, go] = useRoute();
  const health = useAsync(api.health);
  const scenarios = useAsync(api.scenarios);
  const runs = useAsync(api.runs);
  const evalData = useAsync(api.eval, route.tab === "eval");
  const [menuOpen, setMenuOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // No answer at all, or a gateway error from the dev proxy when the backend is not running.
  const unreachable = (e: ApiError | null) => e !== null && (e.status === 0 || e.status >= 502);
  const down = (unreachable(health.error) && !health.data) || (unreachable(scenarios.error) && !scenarios.data);
  const list = scenarios.data;
  const scenario = useMemo(() => {
    if (!list || list.length === 0) return null;
    return list.find((s) => s.id === route.scenarioId) ?? list[0];
  }, [list, route.scenarioId]);

  const runList = runs.data ?? [];
  const latest = scenario ? runList.find((r) => r.scenario_id === scenario.id)?.run_id ?? null : null;
  const runId = route.runId ?? latest;
  const runsReady = runs.data !== null || runs.error !== null;

  useEffect(() => {
    setStartError(null);
  }, [scenario?.id]);

  useEffect(() => {
    document.title = route.tab === "eval" ? "Eval - Buyer Agent" : scenario ? `${scenario.title} - Buyer Agent` : "Buyer Agent";
  }, [route.tab, scenario]);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const reloadRuns = runs.reload;
  const startRun = useCallback(async () => {
    if (!scenario) return;
    setStarting(true);
    setStartError(null);
    try {
      const res = await api.startRun(scenario.id);
      go({ tab: "run", scenarioId: scenario.id, runId: res.run_id });
      reloadRuns();
    } catch (e) {
      setStartError(e instanceof ApiError ? e.message : "The run could not start.");
    } finally {
      setStarting(false);
    }
  }, [scenario, go, reloadRuns]);

  const retryAll = () => {
    health.reload();
    scenarios.reload();
    runs.reload();
  };

  let content;
  if (route.tab === "eval") {
    content = down ? <ApiDown onRetry={retryAll} /> : <EvalView evalData={evalData} scenarios={list} />;
  } else if (down) {
    content = <ApiDown onRetry={retryAll} />;
  } else if (scenarios.error && !list) {
    content = (
      <div className="page">
        <ErrorBlock title="Couldn't load the scenarios" onRetry={scenarios.reload}>{scenarios.error.message}</ErrorBlock>
      </div>
    );
  } else if (!scenario || !runsReady) {
    content = <div className="page"><PageSkeleton /></div>;
  } else {
    content = (
      <RunView
        key={scenario.id}
        scenario={scenario}
        runs={runList}
        runId={runId}
        health={health.data}
        starting={starting}
        startError={startError}
        onRun={startRun}
        onPick={(id) => go({ tab: "run", scenarioId: scenario.id, runId: id })}
        onSettled={reloadRuns}
      />
    );
  }

  return (
    <div className="app">
      <Sidebar
        scenarios={list}
        failed={!!scenarios.error && !list}
        runs={runList}
        route={{ ...route, scenarioId: scenario?.id ?? route.scenarioId }}
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        health={health.data}
        down={down}
      />
      <TopBar route={{ ...route, scenarioId: scenario?.id ?? route.scenarioId }} health={health.data} down={down} onMenu={() => setMenuOpen(true)} menuOpen={menuOpen} />
      <main className="sheet" id="main">
        {content}
      </main>
    </div>
  );
}

function ApiDown({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="page">
      <header className="title-row">
        <div className="title-block">
          <h1>Can't reach the API</h1>
          <p className="situation">The backend did not answer at /api. Start it from the backend folder with uvicorn app.main:app, then retry.</p>
        </div>
      </header>
      <div style={{ marginTop: 24 }}>
        <ErrorBlock title="No connection to the backend" onRetry={onRetry}>
          Nothing has been lost: finished runs are read from their trace files once the server is back.
        </ErrorBlock>
      </div>
    </div>
  );
}
