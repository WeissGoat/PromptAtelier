import { EyeOff, ListOrdered, Play, RefreshCw, RotateCcw, Search, Shuffle, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../api/client";
import type { NodePoolCandidate, NodePoolScanResponse } from "../api/types";
import { listNodePoolCollections, scanNodePool } from "../randomNodes/api";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import type { NodePoolSpec, NodeVariantSlot } from "../workspace/types";
import { ClassifyFilterEditor } from "./ClassifyFilterEditor";
import { NodePreviewImage } from "./NodePreviewImage";

const roleLabels: Record<NodeVariantSlot["role"], string> = {
  artist: "Artist",
  character: "Character",
  action: "Action",
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
        limit: 48,
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

  const isSequential = spec.drawMode === "sequential";
  const poolTotal = scan?.source_total ?? 0;
  const cursor = slot.poolCursor ?? 0;
  const canExclude = spec.source.type === "folder";

  function exclude(item: NodePoolCandidate, position: number) {
    if (spec!.source.exclude_names.includes(item.name)) return;
    updateSource({ exclude_names: [...spec!.source.exclude_names, item.name] });
    // 排除已经跑过的成员后，后面的都前移一位；游标跟着退一位，下一个还是原来那个节点。
    if (isSequential && position < cursor) workspace.setPoolCursor(slot.slotId, cursor - 1);
  }

  return (
    <section className="random-node-editor">
      <div className="panel-title node-editor-title">
        <div>
          <h2>节点组 · {roleLabels[slot.role]}</h2>
          <small>
            {slot.mode === "compare" ? "Compare" : "Primary"} · {isSequential
              ? "按顺序一个一个跑，每次出图后前进一位"
              : "普通出图每轮随机抽一个，Compare 同一组内共享"}
          </small>
        </div>
        <button aria-label="关闭节点组编辑器" className="icon-button" onClick={workspace.closeEditor} title="关闭" type="button"><X size={17} /></button>
      </div>

      <div className="node-group-mode">
        <div aria-label="抽取方式" className="segmented-control node-group-mode-toggle" role="group">
          <button aria-pressed={!isSequential} className={!isSequential ? "active" : ""} onClick={() => update({ ...spec, drawMode: "random" })} type="button">
            <Shuffle size={14} /> 随机抽取
          </button>
          <button aria-pressed={isSequential} className={isSequential ? "active" : ""} onClick={() => update({ ...spec, drawMode: "sequential" })} type="button">
            <ListOrdered size={14} /> 按顺序
          </button>
        </div>
        {isSequential && scan ? (
          <span className="node-group-cursor">
            {cursor >= poolTotal ? "已跑完" : <>下一个：<strong>#{cursor + 1}</strong> / {poolTotal}</>}
            <button aria-label="重置顺序位置" className="icon-button" onClick={() => workspace.resetPoolCursor(slot.slotId)} title="回到第一个" type="button"><RotateCcw size={13} /></button>
          </span>
        ) : null}
      </div>

      <div className="random-source-grid">
        <label className="field compact">
          <span>来源</span>
          <select
            aria-label="随机节点来源"
            onChange={(event) => {
              const nextType = event.target.value as NodePoolSpec["source"]["type"];
              const defaultValue = nextType === "folder" ? (slot.role === "action" ? "new" : ".") : "";
              updateSource({ type: nextType, value: defaultValue });
            }}
            value={spec.source.type}
          >
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
            <span>{spec.source.type === "folder" ? `相对 ${roleLabels[slot.role]} 根目录` : `相对 ${roleLabels[slot.role]} 根目录的 Glob`}</span>
            <input aria-label="随机节点来源值" onChange={(event) => updateSource({ value: event.target.value })} placeholder={spec.source.type === "folder" ? (slot.role === "action" ? "new" : ".") : (slot.role === "action" ? "new/*足部*" : "*")} value={spec.source.value} />
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
          <ClassifyFilterEditor
            facets={scan?.facets ?? {}}
            onChange={(classify) => update({ ...spec, filters: { classify } })}
            value={spec.filters.classify}
          />
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
        <label className="node-search random-candidate-search"><Search size={16} /><input aria-label="搜索节点组成员" onChange={(event) => setQuery(event.target.value)} placeholder="搜索成员" value={query} /></label>
        <span>{scan ? `${scan.total} 个成员` : "等待扫描"}</span>
      </div>
      <div className="node-group-grid" onScroll={(event) => {
        const element = event.currentTarget;
        if (!busy && scan?.has_more && element.scrollTop + element.clientHeight >= element.scrollHeight - 80) {
          void runScan({ refresh: false, append: true });
        }
      }}>
        {items.map((item, index) => {
          const position = item.position ?? (scan?.offset ?? 0) + index;
          const isCurrent = isSequential && position === cursor;
          const isDone = isSequential && position < cursor;
          return (
            <article className={`node-group-member${isCurrent ? " current" : ""}${isDone ? " done" : ""}`} key={item.ref} title={item.relative ?? item.name}>
              <NodePreviewImage className="node-group-member-image" hasPreview={item.has_preview} name={item.name} nodeRef={item.ref} size={240} />
              <span className="node-group-order">#{position + 1}</span>
              {isCurrent ? <span className="node-group-next">下一个</span> : null}
              <div className="node-group-member-name">{item.name}</div>
              <div className="node-group-member-actions">
                {isSequential && !isCurrent ? (
                  <button aria-label={`从 ${item.name} 开始`} onClick={() => workspace.setPoolCursor(slot.slotId, position)} title="从这里开始按顺序跑" type="button"><Play size={12} /></button>
                ) : null}
                {canExclude ? (
                  <button aria-label={`排除 ${item.name}`} onClick={() => exclude(item, position)} title="从节点组里排除（写进名称排除）" type="button"><EyeOff size={12} /></button>
                ) : null}
              </div>
            </article>
          );
        })}
        {busy ? <div className="random-candidate-loading">正在扫描...</div> : null}
        {!busy && spec.source.value && !items.length ? <div className="empty-workspace">没有匹配的节点。</div> : null}
      </div>
      {scan?.warnings.length ? <details className="random-scan-warnings"><summary>扫描警告 {scan.warnings.length}</summary><pre>{scan.warnings.join("\n")}</pre></details> : null}
    </section>
  );
}
