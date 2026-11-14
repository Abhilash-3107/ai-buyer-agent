import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage, HarnessStep, RunSummary, TraceEvent } from "../types";
import type { Connection } from "../hooks/useRun";
import { buildTimeline, argEntries, isId, resultSummary, stepView, toolGroup, writeStatus, writeTone, type Call, type Generation as Gen, type Item, type ToolUse } from "../lib/trace";
import { compact, count, plural, seconds } from "../lib/format";
import { humanize, outcomeMessage, preloadName } from "../lib/words";
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

/** What the harness has to say about a call: the validator's violations for a step, or the result's message or error otherwise. */
function WriteBox({ call, step }: { call: Call; step?: HarnessStep }) {
  const r = call.result;
  if (step) {
    const violations: { code: string; severity: string; message: string }[] = r?.violations ?? [];
    if (violations.length === 0) return null;
    return (
      <div className={`write ${stepView(step).tone}`}>
        <ul>
          {violations.map((v, i) => (
            <li key={i}>
              <span className="code">{v.code}</span>
              {v.severity === "warning" ? "Warning: " : ""}
              {v.message}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  if (!r) return null;
  const status = writeStatus(r);
  if (status) return r.message ? <div className={`write ${writeTone(status)}`}><p>{r.message}</p></div> : null;
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
    <div className={compact ? "py-1.5" : undefined}>
      <button type="button" className="row-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Chevron open={open} />
        <span className="call-name">{call.name}</span>
        {compact && <span className={`call-result ${summary.tone === "neutral" ? "" : summary.tone}`}>{summary.text}</span>}
      </button>
      <div className="call-args"><Args args={call.args} /></div>
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

function StepRow({ step, call }: { step: HarnessStep; call: Call }) {
  const v = stepView(step);
  const violations = step.stage === "validator" && step.status !== "PASSED";
  return (
    <>
      <div className="step-line">
        <span className="step-label">{v.label}</span>
        <span className={`pill ${v.tone === "neutral" ? "" : v.tone}`}>{v.text}</span>
      </div>
      {violations ? <WriteBox call={call} step={step} /> : step.detail && <p className="step-detail">{step.detail}</p>}
    </>
  );
}

function ExecRow({ call }: { call: Call }) {
  const summary = resultSummary(call);
  return (
    <>
      <div className="step-line">
        <span className="step-label">Ran <span className="call-name">{call.name}</span></span>
        <span className={`call-result ${summary.tone === "neutral" ? "" : summary.tone}`}>{summary.text}</span>
      </div>
      <WriteBox call={call} />
    </>
  );
}

function Preload({ calls }: { calls: Call[] }) {
  const [open, setOpen] = useState(false);
  const names = [...new Set(calls.map((c) => preloadName(c.name)))];
  return (
    <div>
      <button type="button" className="row-btn preload" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Chevron open={open} />
        <span>Preloaded {calls.length} reads: {names.join(", ")}</span>
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

const ROLES: Record<string, string> = { system: "System", user: "User", assistant: "Assistant", tool: "Tool result" };

/** JSON text is shown indented, anything else as it is. */
function pretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function Message({ message }: { message: ChatMessage }) {
  return (
    <div>
      <h4>
        {ROLES[message.role] ?? humanize(message.role)}
        {message.tool_call_id && <span className="mono"> {message.tool_call_id}</span>}
      </h4>
      {message.content ? <pre>{message.role === "tool" ? pretty(message.content) : message.content}</pre> : null}
      {(message.tool_calls ?? []).map((c) => (
        <pre key={c.id}>{`${c.function.name} ${pretty(c.function.arguments)}`}</pre>
      ))}
    </div>
  );
}

function GenerationInput({ gen }: { gen: Gen }) {
  const [full, setFull] = useState(false);
  const shown = full ? gen.context : gen.delta;
  return (
    <>
      <p className="note-line">
        {full ? `All ${plural(shown.length, "message")} sent so far` : `${plural(shown.length, "new message")}`}
        {gen.n > 1 && (
          <>
            {" · "}
            <button type="button" className="link-btn" aria-pressed={full} onClick={() => setFull((f) => !f)}>
              {full ? "Show only new messages" : "Show full context"}
            </button>
          </>
        )}
      </p>
      <div className="json">
        {shown.map((m, i) => (
          <Message key={i} message={m} />
        ))}
      </div>
    </>
  );
}

function GenerationTools({ gen, use }: { gen: Gen; use: ToolUse }) {
  return (
    <div className="tool-list">
      {(["Read", "Calculate", "Write", "Finish"] as const).map((group) => {
        const tools = gen.tools.filter((t) => toolGroup(t.function.name) === group);
        if (tools.length === 0) return null;
        return (
          <div key={group}>
            <h4>{group}</h4>
            {tools.map((t) => {
              const n = use.calls[t.function.name] ?? 0;
              return (
                <details key={t.function.name} className={`tool ${n === 0 ? "unused" : ""}`}>
                  <summary>
                    <span className="call-name">{t.function.name}</span>
                    <span className="call-result">
                      {n > 0 ? plural(n, "call") : use.preloaded.has(t.function.name) ? "preloaded by the harness" : "unused"}
                    </span>
                  </summary>
                  <p className="muted">{t.function.description}</p>
                  <pre>{JSON.stringify(t.function.parameters, null, 2)}</pre>
                </details>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function GenerationOutput({ gen }: { gen: Gen }) {
  if (!gen.responded) return <p className="note-line">No response was recorded.</p>;
  return (
    <div className="json">
      <div>
        <h4>Text</h4>
        {gen.text ? <p className="trace-text">{gen.text}</p> : <p className="muted">No text, only tool calls.</p>}
      </div>
      {gen.toolCalls.length > 0 && (
        <div>
          <h4>Tool calls</h4>
          {gen.toolCalls.map((c) => (
            <div key={c.id} className="py-1">
              <span className="call-name">{c.name}</span>
              <div className="call-args" style={{ marginLeft: 0 }}><Args args={c.arguments} /></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type GenTab = "input" | "tools" | "output";

function Generation({ gen, use, finished }: { gen: Gen; use: ToolUse; finished: boolean }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<GenTab>("input");
  const tabs: GenTab[] = gen.n === 1 ? ["input", "tools", "output"] : ["input", "output"];
  const meta = gen.responded
    ? [
        gen.tokensIn !== null && `${compact(gen.tokensIn)} in / ${compact(gen.tokensOut ?? 0)} out`,
        gen.latency !== null && seconds(gen.latency),
      ].filter(Boolean).join(" · ")
    : finished ? "No response" : "Waiting for the model";
  const sub = [gen.model, gen.finishReason && humanize(gen.finishReason).toLowerCase()].filter(Boolean).join(" · ");
  return (
    <div>
      <button type="button" className="row-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Chevron open={open} />
        <span className="gen-name">Generation {gen.n}</span>
        <span className="call-result num">{meta}</span>
      </button>
      {sub && <div className="call-args">{sub}</div>}
      {!open && gen.text && <p className="gen-text">{gen.text}</p>}
      {open && (
        <div className="gen-detail">
          <div className="subtabs" role="tablist">
            {tabs.map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
                {humanize(t)}
              </button>
            ))}
          </div>
          {tab === "input" && <GenerationInput gen={gen} />}
          {tab === "tools" && <GenerationTools gen={gen} use={use} />}
          {tab === "output" && <GenerationOutput gen={gen} />}
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

function Body({ item }: { item: Item }) {
  switch (item.kind) {
    case "started": {
      const t = item.trigger;
      return (
        <p>
          Run started, trigger: {humanize(String(t.type ?? "unknown")).toLowerCase()} <Id value={String(t.rec_id ?? t.event_id ?? item.sku)} />
        </p>
      );
    }
    case "preload":
      return <Preload calls={item.calls} />;
    case "generation":
      return <Generation gen={item.gen} use={item.use} finished={item.finished} />;
    case "call":
      return <CallRow call={item.call} />;
    case "step":
      return <StepRow step={item.step} call={item.call} />;
    case "exec":
      return <ExecRow call={item.call} />;
    case "verification":
      return (
        <div className={`notice ${item.passed ? "pos" : "neg"}`}>
          <strong>
            {item.passed ? "Verifier passed" : `Verifier found ${item.findings.length === 1 ? "a problem" : `${item.findings.length} problems`}`}
            <span style={{ fontWeight: 400 }}>{` on try ${item.round}`}</span>
          </strong>
          <Findings findings={item.findings} />
        </div>
      );
    case "flagged":
      return (
        <div className="notice warn">
          <strong>Flagged for a human</strong>
          <span>{item.message}</span>
        </div>
      );
    case "error":
      return (
        <div className="notice neg">
          <strong>The run stopped with an error</strong>
          <span>{item.message}</span>
        </div>
      );
    case "note":
      return <p className="note-line">{item.text}</p>;
    case "finished":
      return item.outcome === "DECIDED" ? (
        <p className="note-line num">
          Run finished: {plural(item.steps, "generation")}, {seconds(item.latency)}, {count(item.tokensIn)} tokens in, {count(item.tokensOut)} out
        </p>
      ) : (
        <div className="notice neg">
          <strong>{humanize(item.outcome)}</strong>
          <span>{outcomeMessage(item.outcome)}</span>
        </div>
      );
  }
}

/** One row of the single thread: a rail and tag saying who acted, then what happened. */
function Row({ item }: { item: Item }) {
  return (
    <div className={`trace-item ${item.actor} d${item.depth}`}>
      <span className="tag">{item.actor === "llm" ? "LLM" : "HARNESS"}</span>
      <div className="trace-body">
        <Body item={item} />
      </div>
    </div>
  );
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
