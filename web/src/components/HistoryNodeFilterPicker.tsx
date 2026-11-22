import { Check, LoaderCircle, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { HistoryIndexedNode, HistoryIndexingStatus, HistoryNodeFilter, HistoryNodesResponse } from "../api/types";
import { HISTORY_ROLE_LABELS, sameNodeFilter } from "../history/historyFilter";

const ROLE_TABS: Array<{ key: string; label: string }> = [
  { key: "all", label: "全部" },
  { key: "artist", label: "画风" },
  { key: "character", label: "角色" },
  { key: "action", label: "动作" },
  { key: "clothing", label: "服装" },
];

type HistoryNodeFilterPickerProps = {
  selected: HistoryNodeFilter[];
  onToggle: (node: HistoryNodeFilter) => void;
};

export function HistoryNodeFilterPicker({ selected, onToggle }: HistoryNodeFilterPickerProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestId = useRef(0);
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState("all");
  const [query, setQuery] = useState("");
  const [nodes, setNodes] = useState<HistoryIndexedNode[]>([]);
  const [indexing, setIndexing] = useState<HistoryIndexingStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const current = ++requestId.current;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      const params = new URLSearchParams({ limit: "120" });
      if (role !== "all") params.set("role", role);
      if (query.trim()) params.set("q", query.trim());
      void apiGet<HistoryNodesResponse>(`/history/nodes?${params.toString()}`)
        .then((res) => {
          if (current !== requestId.current) return;
          setNodes(res.nodes);
          setIndexing(res.indexing);
        })
        .catch((err) => {
          if (current !== requestId.current) return;
          setError(errorMessage(err));
        })
        .finally(() => {
          if (current === requestId.current) setLoading(false);
        });
    }, query ? 180 : 0);
    return () => window.clearTimeout(timer);
  }, [open, role, query]);

  return (
    <div className="history-node-picker" ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        className={selected.length ? "history-node-trigger active" : "history-node-trigger"}
        onClick={() => {
          setOpen((prev) => {
            const next = !prev;
            if (next) window.setTimeout(() => inputRef.current?.focus(), 0);
            return next;
          });
        }}
        type="button"
      >
        <SlidersHorizontal size={14} />
        <span>按节点筛选</span>
        {selected.length ? <span className="history-node-trigger-count">{selected.length}</span> : null}
      </button>

      {open ? (
        <div aria-label="选择筛选节点" className="history-node-popover" role="dialog">
          <div className="history-node-popover-head">
            <div className="history-node-role-tabs" role="tablist">
              {ROLE_TABS.map((tab) => (
                <button
                  aria-selected={role === tab.key}
                  className={role === tab.key ? `active role-tab-${tab.key}` : `role-tab-${tab.key}`}
                  key={tab.key}
                  onClick={() => setRole(tab.key)}
                  role="tab"
                  type="button"
                >
                  {tab.key !== "all" ? <span className={`history-role-dot role-${tab.key}`} aria-hidden="true" /> : null}
                  {tab.label}
                </button>
              ))}
            </div>
            <button aria-label="关闭节点筛选面板" className="icon-button btn-ghost" onClick={() => setOpen(false)} type="button">
              <X size={14} />
            </button>
          </div>

          <label className="history-node-search">
            <Search size={14} />
            <input
              aria-label="搜索历史节点"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索历史出图里用过的节点名…"
              ref={inputRef}
              value={query}
            />
            {query ? (
              <button aria-label="清空节点搜索" className="icon-button btn-ghost" onClick={() => setQuery("")} type="button">
                <X size={13} />
              </button>
            ) : null}
          </label>

          {indexing?.running ? (
            <div className="history-indexing-hint">
              <LoaderCircle className="spin" size={13} />
              <span>正在索引历史图片 {indexing.indexed} / {indexing.total}…</span>
            </div>
          ) : null}

          <div className="history-node-options">
            {loading && !nodes.length ? <div className="history-node-empty">加载中…</div> : null}
            {!loading && error ? <div className="history-node-empty field-error">{error}</div> : null}
            {!loading && !error && !nodes.length ? (
              <div className="history-node-empty">没有找到匹配的节点记录</div>
            ) : null}
            {nodes.map((item) => {
              const filter: HistoryNodeFilter = { role: item.role, name: item.name, ref: item.ref };
              const active = selected.some((entry) => sameNodeFilter(entry, filter));
              return (
                <button
                  aria-pressed={active}
                  className={active ? "history-node-option active" : "history-node-option"}
                  key={`${item.role}\u0000${item.ref || item.name}`}
                  onClick={() => onToggle(filter)}
                  title={item.ref || item.name}
                  type="button"
                >
                  <span className={`history-role-dot role-${item.role}`} aria-hidden="true" />
                  <span className="history-node-option-role">{HISTORY_ROLE_LABELS[item.role] ?? item.role}</span>
                  <span className="history-node-option-name">{item.name}</span>
                  <span className="history-node-option-count">{item.count} 张</span>
                  {active ? <Check className="history-node-option-check" size={14} /> : null}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
