import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import type { ChatMessage, RunSummary, TraceEvent } from "../types";
import type { Connection } from "../hooks/useRun";
import { argEntries, buildTree, isId, toolGroup, type Generation as Gen, type NodeType, type ToolUse, type TraceNode } from "../lib/trace";
import { compact, count, duration, plural } from "../lib/format";
import { humanize, type Tone } from "../lib/words";
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

/* ---------- the tree ---------- */

const BADGES: Record<NodeType, string> = { agent: "AGENT", span: "SPAN", generation: "GEN", tool: "TOOL", guardrail: "GUARD", event: "EVENT" };
const KINDS: Record<NodeType, string> = { agent: "Run", span: "Span", generation: "Model call", tool: "Tool", guardrail: "Check", event: "Event" };
const toneClass = (tone?: Tone) => (tone && tone !== "neutral" ? tone : "");
/** Checks and events happen at a moment, so only the rest have a duration. */
const timed = (n: TraceNode): n is TraceNode & { end: number } => n.end !== null && n.type !== "guardrail" && n.type !== "event";
const defaultOpen = (n: TraceNode) => n.id !== "preload";

interface Row {
  node: TraceNode;
  parent?: TraceNode;
}

/** The rows on screen, in order: a collapsed node hides its children. */
function flatten(node: TraceNode, isOpen: (n: TraceNode) => boolean, parent?: TraceNode, out: Row[] = []): Row[] {
  out.push({ node, parent });
  if (isOpen(node)) for (const c of node.children) flatten(c, isOpen, node, out);
  return out;
}

function everyNode(node: TraceNode, out = new Map<string, TraceNode>()): Map<string, TraceNode> {
  out.set(node.id, node);
  for (const c of node.children) everyNode(c, out);
  return out;
}

interface TreeProps {
  selectedId: string;
  stop: string; // the one item in the tab order
  isOpen: (n: TraceNode) => boolean;
  onSelect: (id: string) => void;
  onToggle: (n: TraceNode) => void;
}

function Branch({ node, depth, t }: { node: TraceNode; depth: number; t: TreeProps }) {
  const kids = node.children.length > 0;
  const expanded = kids && t.isOpen(node);
  const sub = [timed(node) && duration(node.end - node.start), node.tokens && `${compact(node.tokens.in)} / ${compact(node.tokens.out)} tok`].filter(Boolean).join(" · ");
  const label = `${KINDS[node.type]} ${node.name}${node.summary ? `, ${node.summary.text}` : ""}`;
  return (
    <li
      role="treeitem"
      data-id={node.id}
      aria-level={depth + 1}
      aria-label={label}
      aria-expanded={kids ? expanded : undefined}
      aria-selected={node.id === t.selectedId}
      tabIndex={node.id === t.stop ? 0 : -1}
    >
      <div className="node-row" style={{ "--d": depth } as CSSProperties} onClick={() => t.onSelect(node.id)}>
        {kids ? (
          <span className="node-chev" aria-hidden="true" onClick={(e) => { e.stopPropagation(); t.onToggle(node); }}>
            <Chevron open={expanded} />
          </span>
        ) : (
          <span className="node-chev" aria-hidden="true" />
        )}
        <div className="node-line">
          <span className={`type-badge ${node.type}`} aria-hidden="true">{BADGES[node.type]}</span>
          <span className={`node-name ${node.type === "tool" ? "call-name" : ""}`} title={node.name}>{node.name}</span>
          {node.recovered && <span className="node-chip" aria-hidden="true">from text</span>}
          {node.summary && <span className={`node-sum ${toneClass(node.summary.tone)}`} title={node.summary.text}>{node.summary.text}</span>}
        </div>
        {sub && <div className="node-sub num">{sub}</div>}
      </div>
      {expanded && (
        <ul role="group">
          {node.children.map((c) => (
            <Branch key={c.id} node={c} depth={depth + 1} t={t} />
          ))}
        </ul>
      )}
    </li>
  );
}

/* ---------- the detail pane ---------- */

function Json({ value, empty }: { value: unknown; empty: string }) {
  if (value === undefined) return <p className="note-line">{empty}</p>;
  return (
    <div className="json">
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function Facts({ node }: { node: TraceNode }) {
  const model = node.gen?.model ?? (node.metadata?.model as string | null | undefined);
  const facts: [string, ReactNode][] = [];
  if (node.requestedBy) facts.push(["Requested by", node.requestedBy]);
  if (node.type === "tool" || node.type === "span") facts.push(["Run by", "Code"]);
  if (model) facts.push(["Model", model]);
  if (timed(node)) facts.push(["Duration", duration(node.end - node.start)]);
  if (node.tokens) facts.push(["Tokens", `${count(node.tokens.in)} in, ${count(node.tokens.out)} out`]);
  if (facts.length === 0) return null;
  return (
    <dl className="facts">
      {facts.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A check or event in words: its status, the harness's sentence, and any violations or findings. */
function CheckOutput({ node }: { node: TraceNode }) {
  return (
    <div className={`notice ${node.summary?.tone ?? "neutral"}`}>
      {node.summary && <strong>{node.summary.text}</strong>}
      {node.detail && <span>{node.detail}</span>}
      {node.items && node.items.length > 0 && (
        <ul>
          {node.items.map((f, i) => (
            <li key={i}>
              {f.code && <span className="mono">{f.code} </span>}
              {f.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="detail-sec">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function Detail({ node }: { node: TraceNode }) {
  const gen = node.gen;
  let input: ReactNode = null;
  if (gen) input = <GenerationInput key={node.id} gen={gen} />;
  else if (node.type === "agent" || node.type === "tool") input = <Json value={node.input} empty="No input." />;

  let output: ReactNode;
  if (gen) output = gen.responded ? <GenerationOutput gen={gen} /> : <p className="note-line">{node.summary?.text}.</p>;
  else if (node.type === "agent" || node.type === "tool") output = <Json value={node.output} empty={node.type === "agent" ? "The run has not finished yet." : "Waiting for the result."} />;
  else if (node.type === "span")
    output = (
      <div className="reads">
        {node.children.map((c) => (
          <div key={c.id}>
            <span className="call-name">{c.name}</span>
            <span className={`call-result ${toneClass(c.summary?.tone)}`}>{c.summary?.text}</span>
          </div>
        ))}
      </div>
    );
  else output = <CheckOutput node={node} />;

  return (
    <>
      <header className="detail-head">
        <span className={`type-badge ${node.type}`}>{BADGES[node.type]}</span>
        <h3 className={node.type === "tool" ? "call-name" : undefined}>{node.name}</h3>
        {node.summary && <span className={`pill ${toneClass(node.summary.tone)}`}>{node.summary.text}</span>}
        {node.recovered && <span className="pill warn">Recovered from text</span>}
      </header>
      <Facts node={node} />
      {input && <Section title="Input">{input}</Section>}
      <Section title="Output">{output}</Section>
      {gen && gen.n === 1 && node.use && (
        <details className="disclosure">
          <summary>Tools offered</summary>
          <GenerationTools gen={gen} use={node.use} />
        </details>
      )}
      <details className="disclosure">
        <summary>Metadata</summary>
        <Json value={node.metadata} empty="No metadata." />
      </details>
    </>
  );
}

/* ---------- the trace section ---------- */

function TraceView({ events, live }: { events: TraceEvent[]; live: boolean }) {
  const root = useMemo(() => buildTree(events, !live), [events, live]);
  const index = useMemo(() => everyNode(root), [root]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [pick, setPick] = useState<string | null>(null); // the user's choice; until then a live run follows its newest node
  const pane = useRef<HTMLDivElement>(null);
  const refocus = useRef<string | null>(null);

  const isOpen = (n: TraceNode) => open[n.id] ?? defaultOpen(n);
  const rows = flatten(root, isOpen);
  const selectedId = pick && index.has(pick) ? pick : live ? rows[rows.length - 1].node.id : root.id;
  const selected = index.get(selectedId) ?? root;
  const stop = rows.some((r) => r.node.id === selectedId) ? selectedId : root.id;

  const setExpanded = (n: TraceNode, value: boolean) => setOpen((o) => ({ ...o, [n.id]: value }));
  const select = (id: string, focus = false) => {
    if (focus) refocus.current = id;
    setPick(id);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    const id = (e.target as HTMLElement).closest<HTMLElement>("[role=treeitem]")?.dataset.id;
    const at = rows.findIndex((r) => r.node.id === id);
    if (at < 0) return;
    const { node, parent } = rows[at];
    const kids = node.children.length > 0;
    let to: string | undefined;
    switch (e.key) {
      case "ArrowDown": to = rows[at + 1]?.node.id; break;
      case "ArrowUp": to = rows[at - 1]?.node.id; break;
      case "Home": to = rows[0].node.id; break;
      case "End": to = rows[rows.length - 1].node.id; break;
      case "ArrowRight":
        if (kids && !isOpen(node)) setExpanded(node, true);
        else if (kids) to = node.children[0].id;
        break;
      case "ArrowLeft":
        if (kids && isOpen(node)) setExpanded(node, false);
        else to = parent?.id;
        break;
      case "Enter":
      case " ": to = node.id; break;
      default: return;
    }
    e.preventDefault();
    if (to) select(to, true);
  };

  // Keyboard moves take focus along; a followed or chosen row scrolls into view inside the tree pane only.
  useEffect(() => {
    const p = pane.current;
    if (!p) return;
    if (refocus.current) p.querySelector<HTMLElement>(`[data-id="${refocus.current}"]`)?.focus();
    refocus.current = null;
    const row = p.querySelector<HTMLElement>(`[data-id="${selectedId}"] > .node-row`);
    if (!row) return;
    const a = p.getBoundingClientRect();
    const b = row.getBoundingClientRect();
    if (b.top < a.top) p.scrollTop -= a.top - b.top;
    else if (b.bottom > a.bottom) p.scrollTop += b.bottom - a.bottom;
  }, [selectedId, pick]);

  const t: TreeProps = { selectedId, stop, isOpen, onSelect: select, onToggle: (n) => setExpanded(n, !isOpen(n)) };
  return (
    <div className="trace-split">
      <div className="trace-tree" ref={pane}>
        <ul role="tree" aria-label="Trace of the run" onKeyDown={onKeyDown}>
          <Branch node={root} depth={0} t={t} />
        </ul>
        {live && (
          <p className="trace-foot">
            <span className="pulse" aria-hidden="true" />
            {pick === null ? (
              "The agent is working. This view follows the latest step."
            ) : (
              <>
                The agent is working.
                <button type="button" className="link-btn" onClick={() => setPick(null)}>Follow the latest step</button>
              </>
            )}
          </p>
        )}
      </div>
      <section className="trace-detail" aria-label="Details of the selected step">
        <Detail node={selected} />
      </section>
    </div>
  );
}

interface Props {
  hasRun: boolean;
  runId: string | null;
  events: TraceEvent[];
  summary: RunSummary | null;
  connection: Connection;
  onReconnect: () => void;
}

export function Trace({ hasRun, runId, events, summary, connection, onReconnect }: Props) {
  const live = hasRun && summary?.status !== "finished" && !events.some((e) => e.type === "run_finished");
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
      ) : events.length === 0 ? (
        <p className="trace-foot">{connection === "lost" ? "The trace could not be loaded." : "Waiting for the first event."}</p>
      ) : (
        <TraceView key={runId} events={events} live={live} />
      )}
    </section>
  );
}
