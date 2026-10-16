import { ChevronDown, ListOrdered, RefreshCw, RotateCcw, Shuffle, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../api/client";
import type { NodePoolScanResponse } from "../api/types";
import { listNodePoolCollections, scanNodePool } from "../randomNodes/api";
import { withoutSelection } from "../randomNodes/resolve";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { SEQUENTIAL_ROLE_ORDER } from "../generation/sequentialPlan";
import { isSequentialSlot } from "../randomNodes/resolve";
import type { NodePoolSpec, NodeVariantSlot } from "../workspace/types";
import { ClassifyFilterEditor } from "./ClassifyFilterEditor";
import { GroupMembers } from "./GroupMembers";

const roleLabels: Record<NodeVariantSlot["role"], string> = {
  artist: "画风 Artist",
  character: "角色 Character",
  action: "动作 Action",
  clothing: "服装 Clothing",
};

function splitPatterns(value: string): string[] {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

/** 节点组设置：来源、过滤、抽取方式，下面是整组成员（可勾选、可逐个编辑）。 */
export function RandomNodeEditor({ slot }: { slot: NodeVariantSlot }) {
  const workspace = useCustomWorkspace();
  const spec = slot.randomSpec;
  const [collections, setCollections] = useState<Array<{ name: string; item_count: number }>>([]);
  const [scan, setScan] = useState<NodePoolScanResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sourceOpen, setSourceOpen] = useState(!spec?.source.value.trim());
  const requestId = useRef(0);
  // 统计数字看整组（勾选不影响），勾选后的数量由成员列表显示。
  const scanSignature = useMemo(() => JSON.stringify(spec ? withoutSelection(spec) : null), [spec]);

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
      return;
    }
    const timer = window.setTimeout(() => void runScan(true), 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanSignature]);

  useEffect(() => {
    // 来源读不出来时把设置区展开，方便直接改。
    if (error) setSourceOpen(true);
  }, [error]);

  if (!spec) return null;

  function update(next: NodePoolSpec) {
    workspace.updateRandomSpec(slot.slotId, next);
  }

  function updateSource(patch: Partial<NodePoolSpec["source"]>) {
    // 换来源后原来勾选的成员多半不在了，勾选记录一起清掉。
    const changesPool = "type" in patch || "value" in patch;
    const base = changesPool ? withoutSelection(spec!) : spec!;
    update({ ...base, source: { ...spec!.source, ...patch } });
  }

  async function runScan(refresh: boolean) {
    const current = spec;
    if (!current?.source.value.trim()) return;
    const id = ++requestId.current;
    setBusy(true);
    setError("");
    try {
      const response = await scanNodePool({ role: slot.role, spec: withoutSelection(current), offset: 0, limit: 1, refresh });
      if (id !== requestId.current) return;
      setScan(response);
    } catch (requestError) {
      if (id !== requestId.current) return;
      setError(errorMessage(requestError));
      setScan(null);
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }

  const isSequential = spec.drawMode === "sequential";
  const cursor = slot.poolCursor ?? 0;
  // 普通出图里同时按顺序的其他位置（只看 Primary）：多个位置一起按顺序时两两交叉。
  const groups = workspace.state.groups;
  const primarySlots: Record<string, NodeVariantSlot | null | undefined> = {
    artist: groups.artist.primary,
    character: groups.character.primary,
    clothing: groups.character.primary.clothingSlots?.[0],
    action: groups.action.primary,
  };
  const sequentialRoles = SEQUENTIAL_ROLE_ORDER.filter((role) => role === slot.role
    ? isSequential && slot.mode === "primary"
    : isSequentialSlot(primarySlots[role]));
  const crossHint = isSequential && slot.mode === "primary" && sequentialRoles.length > 1
    ? `和 ${sequentialRoles.filter((role) => role !== slot.role).map((role) => roleLabels[role as NodeVariantSlot["role"]]).join("、")} 一起按顺序：两两交叉跑，${roleLabels[sequentialRoles[sequentialRoles.length - 1] as NodeVariantSlot["role"]]} 变化最快。`
    : "";
  const selectedTotal = spec.selection ? spec.selection.refs.length : scan?.stats.total ?? 0;
  const sourceSummary = spec.source.value
    ? `${spec.source.type === "collection" ? "Collection" : spec.source.type === "glob" ? "Glob" : "文件夹"} · ${spec.source.value}${spec.source.recursive ? " · 递归" : ""}`
    : "未配置来源";

  return (
    <section className="random-node-editor">
      <div className="panel-title node-editor-title">
        <div className="node-editor-heading">
          <nav aria-label="编辑位置" className="editor-breadcrumb">
            <span>{roleLabels[slot.role]}</span>
            <span>·</span>
            <span>{slot.mode === "compare" ? "Compare" : "Primary"}</span>
          </nav>
          <h2>节点组</h2>
          <small className="muted">
            {isSequential ? "按顺序一个一个跑，每次出图后前进一位" : "每轮随机抽一个，Compare 同一组内共享"}
            {spec.selection ? " · 只在勾选的成员里抽" : ""}
          </small>
        </div>
        <button aria-label="关闭节点组编辑器" className="icon-button btn-ghost" onClick={workspace.closeEditor} title="关闭" type="button"><X size={17} /></button>
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
            {cursor >= selectedTotal ? "已跑完" : <>下一个：<strong>#{cursor + 1}</strong> / {selectedTotal}</>}
            <button aria-label="重置顺序位置" className="icon-button btn-ghost" onClick={() => workspace.resetPoolCursor(slot.slotId)} title="回到第一个" type="button"><RotateCcw size={13} /></button>
          </span>
        ) : null}
      </div>

      {crossHint ? <div className="editor-hint">{crossHint}</div> : null}
      {isSequential && slot.mode === "compare" ? <div className="editor-hint">Compare 里的节点组按随机抽取；按顺序只用于普通出图（Generate Next / Run All）。</div> : null}

      <details className="group-source" onToggle={(event) => setSourceOpen((event.target as HTMLDetailsElement).open)} open={sourceOpen}>
        <summary>
          <ChevronDown className="chevron" size={14} />
          <span className="group-source-title">来源与过滤</span>
          <span className="group-source-summary" title={sourceSummary}>{sourceSummary}</span>
        </summary>
        <div className="group-source-body">
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
                <span>{spec.source.type === "folder" ? "相对角色根目录的文件夹" : "相对角色根目录的 Glob"}</span>
                <input aria-label="随机节点来源值" onChange={(event) => updateSource({ value: event.target.value })} placeholder={spec.source.type === "folder" ? (slot.role === "action" ? "new" : ".") : (slot.role === "action" ? "new/*足部*" : "*")} value={spec.source.value} />
              </label>
            )}
            <button aria-label="重新扫描" className="icon-button random-refresh" disabled={busy || !spec.source.value.trim()} onClick={() => void runScan(true)} title="重新扫描" type="button"><RefreshCw className={busy ? "spin" : ""} size={16} /></button>
          </div>

          {spec.source.type === "folder" ? (
            <div className="random-folder-options">
              <label className="toggle-row"><input checked={spec.source.recursive} onChange={(event) => updateSource({ recursive: event.target.checked })} type="checkbox" />递归扫描子文件夹</label>
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
        </div>
      </details>

      {scan ? (
        <div className="random-scan-stats">
          <span>原始 {scan.stats.raw_total}</span>
          <span>可用 {scan.stats.total}</span>
          {scan.stats.missing_classify ? <span>未标注 {scan.stats.missing_classify}</span> : null}
          {scan.stats.classify_mismatch ? <span>不匹配 {scan.stats.classify_mismatch}</span> : null}
          {scan.stats.invalid_classify + scan.stats.invalid_node ? <span>无效 {scan.stats.invalid_classify + scan.stats.invalid_node}</span> : null}
        </div>
      ) : null}
      {error ? <div className="alert error-alert" role="alert">{error}</div> : null}

      {spec.source.value.trim() ? <GroupMembers slot={slot} variant="grid" /> : <div className="empty-workspace">先配置来源，节点组成员会显示在这里。</div>}
      {scan?.warnings.length ? <details className="random-scan-warnings"><summary>扫描警告 {scan.warnings.length}</summary><pre>{scan.warnings.join("\n")}</pre></details> : null}
    </section>
  );
}
