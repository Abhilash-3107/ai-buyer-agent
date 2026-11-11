import type { ReactNode } from "react";

export function ErrorBlock({ title, children, onRetry, detail }: { title: string; children?: ReactNode; onRetry?: () => void; detail?: string }) {
  return (
    <div className="error-block" role="alert">
      <h2>{title}</h2>
      {children && <p className="muted">{children}</p>}
      {detail && <p className="small muted">{detail}</p>}
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children, left }: { children: ReactNode; left?: boolean }) {
  return <div className={`empty ${left ? "left" : ""}`}>{children}</div>;
}

export function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <div className="skeleton title" />
      <div className="skeleton line" />
      <div className="skeleton band" />
      <div className="body-grid">
        <div className="skeleton panelbox" />
        <div className="skeleton panelbox" />
      </div>
    </div>
  );
}
