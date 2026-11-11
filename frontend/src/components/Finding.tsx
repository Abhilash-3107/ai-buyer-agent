import type { Finding as FindingT } from "../lib/derive";
import type { Loop } from "../lib/trace";

export function FindingLine({ finding }: { finding: FindingT }) {
  return (
    <div className="finding">
      <p className="finding-main">
        <span className={`verdict ${finding.tone === "neutral" ? "" : finding.tone}`}>{finding.verdict}</span> {finding.text}
      </p>
      {finding.more.length > 0 && (
        <p className="finding-more">
          {finding.more.map((m) => (
            <span key={m.text}>
              <span className={`dot ${m.tone}`} aria-hidden="true" style={m.tone ? undefined : { background: "var(--control)" }} />
              {m.text}
            </span>
          ))}
        </p>
      )}
      <span className="sr-only" role="status">{finding.live}</span>
    </div>
  );
}

/** The signature element: which feedback loop fired in this run, and how it ended. */
export function LoopStrip({ loops }: { loops: [Loop, Loop, Loop] }) {
  return (
    <section className="loops" aria-label="Feedback loops">
      {loops.map((l) => (
        <div key={l.label} className="loop">
          <div className="loop-label">
            <span className={`dot ${l.tone === "idle" || l.tone === "neutral" ? "" : l.tone}`} style={l.tone === "idle" || l.tone === "neutral" ? { background: "var(--control)" } : undefined} aria-hidden="true" />
            {l.label}
          </div>
          <div className={`loop-value ${l.tone === "idle" ? "idle" : ""}`}>{l.text}</div>
        </div>
      ))}
    </section>
  );
}
