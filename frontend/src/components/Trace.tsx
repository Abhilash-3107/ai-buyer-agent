import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { RunSummary, TraceEvent } from "../types";
import type { Connection } from "../hooks/useRun";
import { buildTimeline, argEntries, isId, resultSummary, writeStatus, writeTone, type Call, type Item } from "../lib/trace";
import { count, seconds } from "../lib/format";
import { decisionWord, humanize, outcomeMessage, preloadName } from "../lib/words";
import { Chevron } from "./Icons";
import { Empty } from "./States";

function Id({ value }: { value: string }) {
  return isId(value) ? <span className="mono">{value}</span> : <>{value}</>;
}

function Args({ args }: { args: Record<string, unknown> }) {
  const entries = argEntries(args);
  if (entries.length === 0) return <>no arguments</>;
  return (
    <>
      {entries.map((e, i) => (
        <Fragment key={e.key}>
          {i > 0 && <span aria-hidden="true">{"  "}</span>}
          <span className="k">{e.key} </span>
          <span className="v"><Id value={e.value} /></span>
        </Fragment>
      ))}
    </>
  );
}

function WriteBox({ call }: { call: Call }) {
  const r = call.result;
  if (!r) return null;
  const status = writeStatus(r);
  if (status) {
    const sup = r.supplier;
    const violations: { code: string; severity: string; message: string }[] = r.violations ?? [];
    return (
      <div className={`write ${writeTone(status)}`}>
        {sup ? (
          <p>
            <strong>{sup.status === "REJECTED" ? "Supplier declined" : `Supplier confirmed ${count(sup.confirmed)} of ${count(sup.requested)}`}</strong>
            {sup.confirmed < sup.requested && sup.status !== "REJECTED" ? `, short by ${count(sup.requested - sup.confirmed)}` : ""}
            {sup.message ? `. ${sup.message}` : ""}
          </p>
        ) : (
          // A refusal already lists its violations; repeating the joined message above them adds nothing.
          r.message && !(violations.length > 0 && (status === "BLOCKED" || status === "NEEDS_JUSTIFICATION")) && <p>{r.message}</p>
        )}
        {violations.length > 0 && (
          <ul>
            {violations.map((v, i) => (
              <li key={i}>
                <span className="code">{v.code}</span>
                {v.severity === "warning" ? "Warning: " : ""}
                {v.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  // The verifier's rejection of a decision is shown once, by its own notice further down.
  if (call.name === "submit_decision" && typeof r.error === "string" && r.error.startsWith("Verification")) return null;
  if (r.ok === false && typeof r.error === "string") {
    return (
      <div className="write neg">
        <p>{r.error}</p>
      </div>
    );
  }
  return null;
}

function CallRow({ call, compact = false }: { call: Call; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const summary = resultSummary(call);
  return (
    <div className={compact ? "py-1.5" : "trace-item"}>
      <button type="button" className="row-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Chevron open={open} />
        <span className="call-name">{call.name}</span>
        <span className={`call-result ${summary.tone === "neutral" ? "" : summary.tone}`}>{summary.text}</span>
      </button>
      <div className="call-args"><Args args={call.args} /></div>
      {!compact && <WriteBox call={call} />}
      {open && (
        <div className="json">
          <div>
            <h4>Arguments</h4>
            <pre>{JSON.stringify(call.args, null, 2)}</pre>
          </div>
          <div>
            <h4>Result</h4>
            <pre>{call.result === undefined ? "Waiting for the result" : JSON.stringify(call.result, null, 2)}</pre>
          </div>
        </div>
      )}
    </div>
  );
}

function Preload({ calls }: { calls: Call[] }) {
  const [open, setOpen] = useState(false);
  const names = [...new Set(calls.map((c) => preloadName(c.name)))];
  return (
    <div className="trace-item">
      <button type="button" className="row-btn preload" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Chevron open={open} />
        <span>Loaded {names.join(", ")}</span>
      </button>
      {open && (
        <div style={{ marginLeft: 20 }}>
          {calls.map((c) => (
            <CallRow key={c.seq} call={c} compact />
          ))}
        </div>
      )}
    </div>
  );
}

function Findings({ findings }: { findings: { code: string; message: string }[] }) {
  if (findings.length === 0) return null;
  return (
    <ul>
      {findings.map((f, i) => (
        <li key={i}>
          <span className="mono">{f.code}</span> {f.message}
        </li>
      ))}
    </ul>
  );
}

function Row({ item }: { item: Item }) {
  switch (item.kind) {
    case "preload":
      return <Preload calls={item.calls} />;
    case "turn":
      return (
        <div className="trace-item turn">
          <span>Turn {item.turn}</span>
          {item.latency !== null && item.latency > 0 && <span className="num" style={{ fontWeight: 400 }}>{seconds(item.latency)}</span>}
        </div>
      );
    case "text":
      return <div className="trace-item"><p className="trace-text">{item.text}</p></div>;
    case "call":
      return <CallRow call={item.call} />;
    case "decision": {
      const d = item.data;
      return (
        <div className="trace-item">
          <p className="decision-line">
            {item.revised ? "Revised decision" : "Decision"}: {decisionWord(d.decision)}
            {typeof d.new_units === "number" ? `, ${count(d.new_units)} units` : ""}
            {d.confidence ? `, confidence ${d.confidence}` : ""}
          </p>
          {d.summary && <p className="muted" style={{ marginTop: 2 }}>{d.summary}</p>}
        </div>
      );
    }
    case "verification":
      return (
        <div className="trace-item">
          <div className={`notice ${item.passed ? "pos" : "neg"}`}>
            <strong>
              {item.passed ? "Verifier passed" : `Verifier found ${item.findings.length === 1 ? "a problem" : `${item.findings.length} problems`}`}
              <span style={{ fontWeight: 400 }}>{` on try ${item.round}`}</span>
            </strong>
            <Findings findings={item.findings} />
          </div>
        </div>
      );
    case "flagged":
      return (
        <div className="trace-item">
          <div className="notice warn">
            <strong>Flagged for a human</strong>
            <span>{item.message}</span>
          </div>
        </div>
      );
    case "error":
      return (
        <div className="trace-item">
          <div className="notice neg">
            <strong>The run stopped with an error</strong>
            <span>{item.message}</span>
          </div>
        </div>
      );
    case "note":
      return <div className="trace-item"><p className="note-line">{item.text}</p></div>;
    case "finished":
      return item.outcome === "DECIDED" ? (
        <div className="trace-item">
          <p className="note-line num">
            Finished in {item.steps} {item.steps === 1 ? "turn" : "turns"}, {seconds(item.latency)}, {count(item.tokensIn)} tokens in, {count(item.tokensOut)} out
          </p>
        </div>
      ) : (
        <div className="trace-item">
          <div className="notice neg">
            <strong>{humanize(item.outcome)}</strong>
            <span>{outcomeMessage(item.outcome)}</span>
          </div>
        </div>
      );
  }
}

interface Props {
  hasRun: boolean;
  events: TraceEvent[];
  summary: RunSummary | null;
  connection: Connection;
  onReconnect: () => void;
}

export function Trace({ hasRun, events, summary, connection, onReconnect }: Props) {
  const items = useMemo(() => buildTimeline(events), [events]);
  const scroller = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const [away, setAway] = useState(false);
  const live = hasRun && summary?.status !== "finished";

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
    atBottom.current = bottom;
    setAway((prev) => (prev === !bottom ? prev : !bottom));
  };

  // A different run opens at the top, a live run follows the newest event only while the user is at the bottom.
  const firstEvent = events[0]?.seq;
  useEffect(() => {
    atBottom.current = true;
    setAway(false);
    if (scroller.current) scroller.current.scrollTop = 0;
  }, [firstEvent, hasRun]);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && live && atBottom.current) el.scrollTop = el.scrollHeight;
  }, [items.length, live]);

  const jump = () => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
    atBottom.current = true;
    setAway(false);
  };

  return (
    <section className="trace" aria-labelledby="trace-h">
      <div className="section-head">
        <h2 id="trace-h">Trace</h2>
        <p className="meta num">
          {!hasRun && "Nothing to show yet"}
          {hasRun && connection === "lost" && (
            <>
              Connection closed.{" "}
              <button type="button" className="link-btn" onClick={onReconnect}>Reconnect</button>
            </>
          )}
          {hasRun && connection === "connecting" && live && events.length > 0 && "Reconnecting"}
          {hasRun && connection !== "lost" && !(connection === "connecting" && live && events.length > 0) && `${count(events.length)} events`}
        </p>
      </div>
      {!hasRun ? (
        <Empty>
          <span>The agent's reads, calls and decision appear here as they happen.</span>
        </Empty>
      ) : (
        <div className="trace-scroll" ref={scroller} onScroll={onScroll} tabIndex={0} role="region" aria-label="Trace of the run">
          {items.length === 0 ? (
            <p className="trace-foot">{connection === "lost" ? "The trace could not be loaded." : "Waiting for the first event."}</p>
          ) : (
            <div className="trace-list">
              {items.map((item) => (
                <Row key={item.key} item={item} />
              ))}
            </div>
          )}
          {live && items.length > 0 && (
            <p className="trace-foot">
              <span className="pulse" aria-hidden="true" />
              The agent is working. This view follows the latest step.
            </p>
          )}
          {live && away && (
            <div className="jump">
              <button type="button" className="btn sm" onClick={jump}>Jump to latest</button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
