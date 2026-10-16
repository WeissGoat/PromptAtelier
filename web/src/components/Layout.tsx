import { FlaskConical, GitCompare, Images, Monitor, Moon, PanelLeft, PanelLeftClose, PanelLeftOpen, Sun } from "lucide-react";
import { type ReactNode, useState } from "react";

import { type ThemePreference, useThemePreference } from "../theme";

export type PageKey = "custom" | "results" | "compare" | "style-lab";

type LayoutProps = {
  page: PageKey;
  onPageChange: (page: PageKey) => void;
  children: ReactNode;
};

const nav = [
  { key: "custom", label: "Custom", hint: "组合节点出图", icon: PanelLeft },
  { key: "results", label: "出图历史", hint: "按批次浏览", icon: Images },
  { key: "compare", label: "Compare", hint: "提示词对比", icon: GitCompare },
  { key: "style-lab", label: "画风工坊", hint: "整理画风语料", icon: FlaskConical },
] as const;

const themes: Array<{ key: ThemePreference; label: string; icon: typeof Sun }> = [
  { key: "light", label: "浅色", icon: Sun },
  { key: "dark", label: "深色", icon: Moon },
  { key: "system", label: "跟随系统", icon: Monitor },
];

const COLLAPSE_STORAGE_KEY = "promptatelier.sidebar-collapsed/v1";

function initialCollapsed(): boolean {
  try {
    return window.localStorage?.getItem(COLLAPSE_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function Layout({ page, onPageChange, children }: LayoutProps) {
  const [theme, setTheme] = useThemePreference();
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  function toggleCollapsed() {
    setCollapsed((current) => {
      try {
        window.localStorage?.setItem(COLLAPSE_STORAGE_KEY, current ? "0" : "1");
      } catch {
        // 记不住也不影响本次折叠。
      }
      return !current;
    });
  }

  return (
    <div className={collapsed ? "app-shell sidebar-collapsed" : "app-shell"}>
      <aside className="sidebar">
        <div className="brand">
          <span aria-hidden="true" className="brand-mark">P</span>
          <div className="brand-text">
            <h1>PromptAtelier</h1>
            <small>提示词工坊</small>
          </div>
        </div>
        <nav aria-label="页面" className="nav-list">
          {nav.map((item) => {
            const Icon = item.icon;
            const active = page === item.key;
            return (
              <button
                aria-current={active ? "page" : undefined}
                className={active ? "active" : ""}
                key={item.key}
                onClick={() => onPageChange(item.key)}
                title={collapsed ? item.label : item.hint}
                type="button"
              >
                <Icon size={17} />
                <span className="nav-label">{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <div aria-label="主题" className="theme-switch" role="radiogroup">
            {themes.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  aria-checked={theme === item.key}
                  aria-label={item.label}
                  className={theme === item.key ? "active" : ""}
                  key={item.key}
                  onClick={() => setTheme(item.key)}
                  role="radio"
                  title={item.label}
                  type="button"
                >
                  <Icon size={14} />
                </button>
              );
            })}
          </div>
          <button
            aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
            className="sidebar-collapse btn-ghost"
            onClick={toggleCollapsed}
            title={collapsed ? "展开侧栏" : "收起侧栏"}
            type="button"
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>
      </aside>
      <div className="app-main">{children}</div>
    </div>
  );
}
