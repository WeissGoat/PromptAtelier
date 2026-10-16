import { FlaskConical, GitCompare, Images, Layers3, PanelLeft } from "lucide-react";
import type { ReactNode } from "react";

import { NovelAIUsageBadge } from "./NovelAIUsageBadge";

export type PageKey = "custom" | "results" | "compare" | "style-lab";

type LayoutProps = {
  page: PageKey;
  onPageChange: (page: PageKey) => void;
  children: ReactNode;
};

const nav = [
  { key: "custom", label: "Custom", icon: PanelLeft },
  { key: "results", label: "出图历史", icon: Images },
  { key: "compare", label: "Compare", icon: GitCompare },
  { key: "style-lab", label: "画风工坊", icon: FlaskConical },
] as const;

export function Layout({ page, onPageChange, children }: LayoutProps) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Layers3 size={20} />
          <h1>PromptAtelier</h1>
        </div>
        <nav className="nav-list">
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={page === item.key ? "active" : ""}
                key={item.key}
                onClick={() => onPageChange(item.key)}
                type="button"
              >
                <Icon size={16} />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <NovelAIUsageBadge />
        </div>
      </aside>
      {children}
    </div>
  );
}
