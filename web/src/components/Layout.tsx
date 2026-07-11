import { Images, Layers3, PanelLeft, Workflow } from "lucide-react";
import type { ReactNode } from "react";

export type PageKey = "custom" | "batch" | "results";

type LayoutProps = {
  page: PageKey;
  onPageChange: (page: PageKey) => void;
  children: ReactNode;
};

const nav = [
  { key: "custom", label: "Custom", icon: PanelLeft },
  { key: "batch", label: "Batch", icon: Workflow },
  { key: "results", label: "Results", icon: Images },
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
      </aside>
      {children}
    </div>
  );
}
