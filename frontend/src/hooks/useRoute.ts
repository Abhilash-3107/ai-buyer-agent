import { useCallback, useEffect, useState } from "react";

export interface Route {
  tab: "run" | "eval";
  scenarioId: string | null;
  runId: string | null;
}

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "eval") return { tab: "eval", scenarioId: null, runId: null };
  return { tab: "run", scenarioId: parts[1] ?? null, runId: parts[2] ?? null };
}

export function href(route: Route): string {
  if (route.tab === "eval") return "#/eval";
  const tail = [route.scenarioId, route.runId].filter(Boolean).map((p) => encodeURIComponent(p as string));
  return `#/run${tail.length ? "/" + tail.join("/") : ""}`;
}

/** Tab, scenario and run live in the URL hash, so a reload or a shared link lands on the same view. */
export function useRoute(): [Route, (next: Route, replace?: boolean) => void] {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const go = useCallback((next: Route, replace = false) => {
    const target = href(next);
    if (replace) window.history.replaceState(null, "", target);
    else window.location.hash = target;
    setRoute(next);
  }, []);
  return [route, go];
}
