import type { Health, RunListItem, Scenario } from "../types";
import { demoLabel, GROUPS } from "../lib/words";
import { href, type Route } from "../hooks/useRoute";
import { BrandMark, CloseIcon, MenuIcon } from "./Icons";

export function ModelBadge({ health, down }: { health: Health | null; down: boolean }) {
  if (down) return <span className="badge neg">API offline</span>;
  if (!health) return <span className="badge">Checking model</span>;
  if (health.demo) return <span className="badge warn" title="Runs use a fixed baseline policy, not the agent's model">{demoLabel(health.model)}</span>;
  return <span className="badge" title={health.local ? "Runs on this machine" : "Runs on a hosted model"}>{health.model}, {health.local ? "local" : "hosted"}</span>;
}

interface SidebarProps {
  scenarios: Scenario[] | null;
  failed: boolean;
  runs: RunListItem[];
  route: Route;
  open: boolean;
  onClose: () => void;
  health: Health | null;
  down: boolean;
}

function lastRunTone(runs: RunListItem[], scenarioId: string): { tone: "pos" | "neg" | "warn" | ""; words: string } {
  const last = runs.find((r) => r.scenario_id === scenarioId); // newest first
  if (!last) return { tone: "", words: "" };
  if (last.status === "running") return { tone: "warn", words: "Last run in progress" };
  if (last.passed === null) return { tone: "neg", words: "Last run stopped before it was scored" };
  return last.passed ? { tone: "pos", words: "Last run matched the expected answer" } : { tone: "neg", words: "Last run missed the expected answer" };
}

export function Sidebar({ scenarios, failed, runs, route, open, onClose, health, down }: SidebarProps) {
  const groups = scenarios ? [...new Set(scenarios.map((s) => s.group))].sort() : [];
  return (
    <aside className={`sidebar ${open ? "open" : ""}`} id="sidebar" aria-label="Scenarios">
      <div className="brand">
        <BrandMark />
        <div>
          <div className="brand-name">Buyer Agent</div>
          <div className="brand-scope">Dark Store North</div>
        </div>
        <button type="button" className="menu-close" aria-label="Close menu" onClick={onClose}>
          <CloseIcon />
        </button>
      </div>
      <nav className="sidebar-scroll" aria-label="Scenarios">
        {scenarios === null && !failed && Array.from({ length: 8 }).map((_, i) => <div key={i} className="skeleton sk-nav" />)}
        {failed && <p className="muted small" style={{ margin: "8px" }}>Scenarios are unavailable until the API answers.</p>}
        {groups.map((g) => (
          <section key={g} aria-labelledby={`group-${g}`}>
            <h2 className="group-label" id={`group-${g}`}>
              <span className="num">{g}</span>
              <span>{GROUPS[g] ?? `Group ${g}`}</span>
            </h2>
            <ul className="list-none p-0 m-0 grid gap-px">
              {scenarios!.filter((s) => s.group === g).map((s) => {
                const current = route.tab === "run" && route.scenarioId === s.id;
                const { tone, words } = lastRunTone(runs, s.id);
                return (
                  <li key={s.id}>
                    <a
                      className="nav-item"
                      href={href({ tab: "run", scenarioId: s.id, runId: null })}
                      aria-current={current ? "page" : undefined}
                      title={s.title}
                      onClick={onClose}
                    >
                      <span className={`dot ${tone}`} aria-hidden="true" />
                      <span className="label">{s.title}</span>
                      {words && <span className="sr-only">{words}</span>}
                    </a>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </nav>
      <div className="sidebar-foot">
        <ModelBadge health={health} down={down} />
      </div>
    </aside>
  );
}

export function TopBar({ route, health, down, onMenu, menuOpen }: { route: Route; health: Health | null; down: boolean; onMenu: () => void; menuOpen: boolean }) {
  return (
    <header className="topbar">
      <button type="button" className="menu-btn" aria-label="Open menu" aria-expanded={menuOpen} aria-controls="sidebar" onClick={onMenu}>
        <MenuIcon />
      </button>
      <span className="topbar-title">Buyer Agent</span>
      <nav className="tabs" aria-label="Views">
        <a className="tab" href={href({ tab: "run", scenarioId: route.scenarioId, runId: null })} aria-current={route.tab === "run" ? "page" : undefined}>
          Run
        </a>
        <a className="tab" href={href({ tab: "eval", scenarioId: null, runId: null })} aria-current={route.tab === "eval" ? "page" : undefined}>
          Eval
        </a>
      </nav>
      <div className="topbar-right">
        <ModelBadge health={health} down={down} />
      </div>
    </header>
  );
}
