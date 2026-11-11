import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { RunSummary, TraceEvent } from "../types";

export type Connection = "idle" | "connecting" | "live" | "ended" | "lost";

export interface RunState {
  events: TraceEvent[];
  summary: RunSummary | null;
  connection: Connection;
  error: ApiError | null;
  refresh: () => void;
  reconnect: () => void;
}

/**
 * One run on screen: its trace over SSE (replayed from seq 1, then live, then `end`) and its summary over REST.
 * EventSource reconnects by itself and the server replays from the start, so events are de-duplicated by seq.
 */
export function useRun(runId: string | null, onSettled?: () => void): RunState {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [connection, setConnection] = useState<Connection>("idle");
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const settled = useRef(onSettled);
  settled.current = onSettled;
  const alive = useRef(0);

  const refresh = useCallback(() => {
    if (!runId) return;
    const token = alive.current;
    api
      .run(runId)
      .then((s) => {
        if (token !== alive.current) return;
        setSummary(s);
        setError(null);
      })
      .catch((e) => {
        if (token === alive.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
      });
  }, [runId]);

  // The summary: once on open, and again after every burst of events while the run is live.
  useEffect(() => {
    alive.current++;
    setEvents([]);
    setSummary(null);
    setError(null);
    if (!runId) {
      setConnection("idle");
      return;
    }
    refresh();
  }, [runId, refresh]);

  // The trace.
  useEffect(() => {
    if (!runId) return;
    setConnection("connecting");
    const token = alive.current;
    const es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
    let lastSeq = 0;
    let buffer: TraceEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | null = null;

    const flush = () => {
      timer = null;
      if (buffer.length === 0 || token !== alive.current) return;
      const batch = buffer;
      buffer = [];
      setEvents((prev) => prev.concat(batch));
    };

    es.onopen = () => setConnection("live");
    es.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data) as TraceEvent;
        if (typeof e?.seq !== "number" || e.seq <= lastSeq) return;
        lastSeq = e.seq;
        buffer.push(e);
        if (timer === null) timer = setTimeout(flush, 60);
      } catch {
        /* a malformed frame is skipped; the next one will still arrive */
      }
    };
    es.addEventListener("end", () => {
      if (timer !== null) clearTimeout(timer);
      flush();
      es.close();
      if (token === alive.current) {
        setConnection("ended");
        refresh();
        settled.current?.();
      }
    });
    es.onerror = () => {
      // CONNECTING: the browser is retrying and the server will replay. CLOSED: it gave up.
      if (token === alive.current) setConnection(es.readyState === EventSource.CLOSED ? "lost" : "connecting");
    };
    return () => {
      if (timer !== null) clearTimeout(timer);
      es.close();
    };
  }, [runId, attempt, refresh]);

  // Keep the PO table, totals and decision current while events arrive.
  const finished = summary?.status === "finished";
  useEffect(() => {
    if (!runId || events.length === 0 || (finished && connection === "ended")) return;
    const t = setTimeout(refresh, 350);
    return () => clearTimeout(t);
  }, [events.length, runId, finished, connection, refresh]);

  const reconnect = useCallback(() => {
    setEvents([]);
    setAttempt((n) => n + 1);
  }, []);

  return { events, summary, connection, error, refresh, reconnect };
}
