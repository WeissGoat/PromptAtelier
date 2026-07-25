import { Dices, RefreshCw, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../api/client";
import type { NodePoolCandidate, NodePoolScanResponse } from "../api/types";
import { listNodePoolCollections, scanNodePool } from "../randomNodes/api";
import { CLASSIFY_FIELDS, CLASSIFY_OPTIONS } from "../randomNodes/spec";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import type { ClassifyFilter, NodePoolSpec, NodeVariantSlot } from "../workspace/types";

const labels: Record<keyof ClassifyFilter, string> = {
  phase: "Phase",
  species: "Species",
  cast: "Cast",
  domain: "Domain",
  subtype: "Subtype",
  pose: "Pose",
  environment: "Environment",
  tone: "Tone",
  flags: "Flags",
  clothing: "Clothing",
};

function splitPatterns(value: string): string[] {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

export function RandomNodeEditor({ slot }: { slot: NodeVariantSlot }) {
  const workspace = useCustomWorkspace();
  const spec = slot.randomSpec;
  const [collections, setCollections] = useState<Array<{ name: string; item_count: number }>>([]);
  const [scan, setScan] = useState<NodePoolScanResponse | null>(null);
  const [items, setItems] = useState<NodePoolCandidate[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  const specSignature = useMemo(() => JSON.stringify(spec), [spec]);

  useEffect(() => {
    let active = true;
    void listNodePoolCollections(slot.role).then((response) => {
      if (active) setCollections(response.items);
    }).catch((requestError) => {
      if (active) setError(errorMessage(requestError));
    });
    return () => { active = false; };
  }, [slot.role]);

  useEffect(() => {
    if (!spec?.source.value.trim()) {
      setScan(null);
      setItems([]);
      return;
    }
    const timer = window.setTimeout(() => void runScan({ refresh: true, append: false }), 300);
    return () => window.clearTimeout(timer);
  }, [specSignature]);

  useEffect(() => {
    if (!spec?.source.value.trim()) return;
    const timer = window.setTimeout(() => void runScan({ refresh: false, append: false }), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  if (!spec) return null;

  function update(next: NodePoolSpec) {
    workspace.updateRandomSpec(slot.slotId, next);
  }

  function updateSource(patch: Partial<NodePoolSpec["source"]>) {
    update({ ...spec!, source: { ...spec!.source, ...patch } });
  }

  function updateFilter(field: keyof ClassifyFilter, values: string[]) {
    update({
      ...spec!,
      filters: {
        classify: { ...spec!.filters.classify, [field]: values },
      },
    });
  }

  async function runScan(options: { refresh: boolean; append: boolean }) {
    const current = spec;
    if (!current?.source.value.trim()) return;
    const id = ++requestId.current;
    setBusy(true);
    setError("");
    try {
      const response = await scanNodePool({
        role: slot.role,
        spec: current,
        q: query,
        offset: options.append ? scan?.next_offset ?? 0 : 0,
        limit: 30,
        refresh: options.refresh,
      });
      if (id !== requestId.current) return;
      setScan(response);
      setItems((previous) => options.append ? [...previous, ...response.items] : response.items);
    } catch (requestError) {
      if (id !== requestId.current) return;
      setError(errorMessage(requestError));
      if (!options.append) {
        setScan(null);
        setItems([]);
      }
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }

  function facetValues(field: keyof ClassifyFilter): string[] {
    return [...new Set([
      ...CLASSIFY_OPTIONS[field],
      ...(scan?.facets[field] ?? []),
      ...spec!.filters.classify[field],
    ])].sort();
  }

  return (
    <section className="random-node-editor">
      <div className="panel-title node-editor-title">
        <div><h2>Random {slot.role}</h2><small>{slot.mode === "compare" ? "Compare" : "Primary"} · 每个实际任务独立抽取</small></div>
        <button aria-label="关闭随机节点编辑器" className="icon-button" onClick={workspace.closeEditor} title="关闭" type="button"><X size={17} /></button>
      </div>

      <div className="random-source-grid">
        <label className="field compact">
          <span>来源</span>
          <select aria-label="随机节点来源" onChange={(event) => updateSource({ type: event.target.value as NodePoolSpec["source"]["type"], value: "" })} value={spec.source.type}>
            <option value="folder">Folder</option>
            <option value="collection">Collection</option>
            <option value="glob">Glob</option>
          </select>
        </label>
        {spec.source.type === "collection" ? (
          <label className="field compact random-source-value">
            <span>Collection</span>
            <select aria-label="随机节点 Collection" onChange={(event) => updateSource({ value: event.target.value })} value={spec.source.value}>
              <option value="">选择 Collection</option>
              {collections.map((item) => <option key={item.name} value={item.name}>{item.name} ({item.item_count})</option>)}
            </select>
          </label>
        ) : (
          <label className="field compact random-source-value">
            <span>{spec.source.type === "folder" ? "相对 design_root 的目录" : "相对 design_root 的 Glob"}</span>
            <input aria-label="随机节点来源值" onChange={(event) => updateSource({ value: event.target.value })} placeholder={spec.source.type === "folder" ? "动作改2/new" : "动作改2/new/*foot*"} value={spec.source.value} />
          </label>
        )}
        <button className="icon-button random-refresh" disabled={busy || !spec.source.value.trim()} onClick={() => void runScan({ refresh: true, append: false })} title="重新扫描" type="button"><RefreshCw className={busy ? "spin" : ""} size={17} /></button>
      </div>

      {spec.source.type === "folder" ? (
        <div className="random-folder-options">
          <label className="toggle-row"><input checked={spec.source.recursive} onChange={(event) => updateSource({ recursive: event.target.checked })} type="checkbox" />递归扫描</label>
          <label className="field compact"><span>名称包含</span><input onChange={(event) => updateSource({ include_names: splitPatterns(event.target.value) })} placeholder="pn_*，逗号分隔" value={spec.source.include_names.join(", ")} /></label>
          <label className="field compact"><span>名称排除</span><input onChange={(event) => updateSource({ exclude_names: splitPatterns(event.target.value) })} placeholder="old, temp" value={spec.source.exclude_names.join(", ")} /></label>
        </div>
      ) : null}

      {slot.role === "action" ? (
        <section className="random-classify-filters">
          <div className="section-title-row"><div><h3>classify.yaml 二次过滤</h3><small>同字段任意命中，不同字段同时满足；不选择则不启用过滤。</small></div></div>
          <div className="classify-filter-grid">
            {CLASSIFY_FIELDS.map((field) => (
              <label className="field compact" key={field}>
                <span>{labels[field]}</span>
                <select aria-label={`classify ${field}`} multiple onChange={(event) => updateFilter(field, Array.from(event.target.selectedOptions, (option) => option.value))} size={Math.min(4, Math.max(2, facetValues(field).length || 2))} value={spec.filters.classify[field]}>
                  {facetValues(field).map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
            ))}
          </div>
        </section>
      ) : null}

      {scan ? (
        <div className="random-scan-stats">
          <span>原始 {scan.stats.raw_total}</span>
          <span>可用 {scan.stats.total}</span>
          <span>未标注 {scan.stats.missing_classify}</span>
          <span>不匹配 {scan.stats.classify_mismatch}</span>
          <span>无效 {scan.stats.invalid_classify + scan.stats.invalid_node}</span>
        </div>
      ) : null}
      {error ? <div className="alert error-alert" role="alert">{error}</div> : null}

      <div className="random-candidate-toolbar">
        <label className="node-search random-candidate-search"><Search size={16} /><input aria-label="搜索随机候选" onChange={(event) => setQuery(event.target.value)} placeholder="搜索扫描结果" value={query} /></label>
        <span>{scan ? `${scan.total} 个候选` : "等待扫描"}</span>
      </div>
      <div className="random-candidate-list" onScroll={(event) => {
        const element = event.currentTarget;
        if (!busy && scan?.has_more && element.scrollTop + element.clientHeight >= element.scrollHeight - 48) {
          void runScan({ refresh: false, append: true });
        }
      }}>
        {items.map((item) => (
          <div className="random-candidate-row" key={item.ref}><Dices size={14} /><span>{item.name}</span><small>{item.relative}</small></div>
        ))}
        {busy ? <div className="random-candidate-loading">正在扫描...</div> : null}
        {!busy && spec.source.value && !items.length ? <div className="empty-workspace">没有匹配的节点。</div> : null}
      </div>
      {scan?.warnings.length ? <details className="random-scan-warnings"><summary>扫描警告 {scan.warnings.length}</summary><pre>{scan.warnings.join("\n")}</pre></details> : null}
    </section>
  );
}
