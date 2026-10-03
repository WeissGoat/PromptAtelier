import { Dices, FilePlus2, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { NodeReadResponse, NodeSummary } from "../api/types";
import { nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeDocument } from "../nodes/types";
import type { NodeVariantSlot } from "../workspace/types";
import { NodePicker } from "./NodePicker";

type NodeSlotProps = {
  label: string;
  slot: NodeVariantSlot;
  placeholder: string;
  onSelect: (response: NodeReadResponse) => void;
  onCreateBlank: () => void;
  onCreateRandom?: () => void;
  onRestore: () => void;
  onClear: () => void;
  onEdit: (response?: NodeReadResponse) => void;
  onEditRandom?: () => void;
  onRemove?: () => void;
  onSelectClothing?: (ref: string | null, node?: NodeDocument | null) => void;
  onAddClothingCompare?: () => void;
  onRemoveClothingCompare?: (clothingSlotId: string) => void;
  onSelectClothingSlot?: (slotId: string, response: NodeReadResponse) => void;
  onCreateBlankClothing?: (slotId: string) => void;
  onCreateRandomClothing?: (slotId: string) => void;
  onRestoreClothing?: (slotId: string) => void;
  onClearClothing?: (slotId: string) => void;
  onEditClothing?: (slotId: string, response?: NodeReadResponse) => void;
  onEditRandomClothing?: (slotId: string) => void;
};

function statusLabel(slot: NodeVariantSlot): string {
  const status = nodeSlotStatus(slot);
  if (status === "original") return "原始节点";
  if (status === "modified") return "临时修改";
  if (status === "temporary") return "空白临时节点";
  if (status === "random") return "随机节点";
  return "未选择";
}

function requiresConfirmation(slot: NodeVariantSlot): boolean {
  const status = nodeSlotStatus(slot);
  return status === "modified" || status === "temporary";
}

function displayName(slot: NodeVariantSlot): string {
  if (slot.sourceKind === "random") {
    const source = slot.randomSpec?.source;
    const isSeq = slot.randomSpec?.drawMode === "sequential";
    const mode = isSeq ? "Sequential" : "Random";
    const cursorInfo = isSeq ? ` · #${(slot.poolCursor ?? 0) + 1}` : "";
    return source?.value ? `${mode} · ${source.type} · ${source.value}${cursorInfo}` : `${mode} · 未配置来源`;
  }
  const name = slot.draftNode?.name || slot.sourceNode?.name || slot.draftNode?.id || "";
  const status = nodeSlotStatus(slot);
  return name && (status === "modified" || status === "temporary") ? `${name} *` : name;
}

export function NodeSlot({
  label,
  slot,
  placeholder,
  onSelect,
  onCreateBlank,
  onCreateRandom,
  onRestore,
  onClear,
  onEdit,
  onEditRandom,
  onRemove,
  onSelectClothing,
  onAddClothingCompare,
  onRemoveClothingCompare,
  onSelectClothingSlot,
  onCreateBlankClothing,
  onCreateRandomClothing,
  onRestoreClothing,
  onClearClothing,
  onEditClothing,
  onEditRandomClothing,
}: NodeSlotProps) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const readRequestId = useRef(0);

  useEffect(() => {
    readRequestId.current += 1;
    setLoading(false);
  }, [slot.sourceRef, slot.sourceNode, slot.draftNode]);

  function invalidatePendingRead() {
    readRequestId.current += 1;
    setLoading(false);
  }

  async function handleSelect(node: NodeSummary) {
    if (requiresConfirmation(slot) && !window.confirm("当前临时修改将被替换，是否继续？")) return;
    const requestId = ++readRequestId.current;
    setLoading(true);
    setError("");
    try {
      const response = await apiGet<NodeReadResponse>(`/nodes/read?${new URLSearchParams({ ref: node.ref, role: slot.role })}`);
      if (requestId !== readRequestId.current) return;
      onSelect(response);
    } catch (requestError) {
      if (requestId !== readRequestId.current) return;
      setError(errorMessage(requestError));
    } finally {
      if (requestId === readRequestId.current) setLoading(false);
    }
  }

  async function handleSelectClothing(node: NodeSummary) {
    try {
      const response = await apiGet<NodeReadResponse>(`/nodes/read?${new URLSearchParams({ ref: node.ref, role: "clothing" })}`);
      onSelectClothing?.(response.ref, response.node);
    } catch {
      onSelectClothing?.(node.ref, null);
    }
  }

  async function handleEdit() {
    if (slot.sourceKind === "random") {
      onEditRandom?.();
      return;
    }
    if (!slot.sourceRef || slot.sourceEditor) {
      onEdit();
      return;
    }
    if (requiresConfirmation(slot) && !window.confirm("当前节点来自旧缓存，重新读取源文件会替换临时修改。是否继续？")) return;
    const requestId = ++readRequestId.current;
    setLoading(true);
    setError("");
    try {
      const response = await apiGet<NodeReadResponse>(`/nodes/read?${new URLSearchParams({ ref: slot.sourceRef, role: slot.role })}`);
      if (requestId !== readRequestId.current) return;
      if (!response.editor) {
        throw new Error("当前后端版本未提供节点源表单，请重启 PromptAtelier Web 服务后重试。");
      }
      onEdit(response);
    } catch (requestError) {
      if (requestId !== readRequestId.current) return;
      setError(errorMessage(requestError));
    } finally {
      if (requestId === readRequestId.current) setLoading(false);
    }
  }

  function runReplacingAction(action: () => void, message: string) {
    if (requiresConfirmation(slot) && !window.confirm(message)) return;
    invalidatePendingRead();
    action();
  }

  return (
    <section className={`node-slot ${slot.mode === "compare" ? "compare-node-slot" : ""}`}>
      <div className="node-slot-header">
        <div className="node-slot-labels">
          {slot.mode === "compare" ? <span className="compare-badge">Compare</span> : null}
          <span className="node-status">{statusLabel(slot)}</span>
        </div>
        <div className="node-slot-actions">
          <button aria-label={`编辑${label}节点`} className="icon-button" disabled={(!slot.draftNode && slot.sourceKind !== "random") || loading} onClick={() => void handleEdit()} title="编辑节点" type="button"><Pencil size={16} /></button>
          <button aria-label={`新建空白${label}节点`} className="icon-button" onClick={() => runReplacingAction(onCreateBlank, "当前临时修改将被替换，是否继续？")} title="新建空白节点" type="button"><FilePlus2 size={16} /></button>
          {onCreateRandom ? <button aria-label={`创建随机${label}节点`} className="icon-button" onClick={() => runReplacingAction(onCreateRandom, "当前节点将被替换为随机节点，是否继续？")} title="随机节点" type="button"><Dices size={16} /></button> : null}
          <button aria-label={`还原${label}节点`} className="icon-button" disabled={!slot.sourceNode} onClick={() => runReplacingAction(onRestore, "当前临时修改将被还原，是否继续？")} title="还原原始节点" type="button"><RotateCcw size={16} /></button>
          {onRemove ? (
            <button aria-label={`删除${label} Compare节点`} className="icon-button" onClick={onRemove} title="删除 Compare 节点" type="button"><Trash2 size={16} /></button>
          ) : null}
        </div>
      </div>
      {slot.sourceKind === "random" ? (
        <button className="random-node-summary" onClick={onEditRandom} type="button">
          <Dices size={16} />
          <span>{displayName(slot)}</span>
        </button>
      ) : (
        <NodePicker
          label={label}
          onClear={() => runReplacingAction(onClear, "当前临时修改将被清除，是否继续？")}
          onSelect={(node) => void handleSelect(node)}
          placeholder={placeholder}
          role={slot.role}
          value={displayName(slot)}
        />
      )}
      {slot.role === "character" ? (
        slot.clothingSlots && slot.clothingSlots.length > 0 ? (
          <div
            className="clothing-overlay-group"
            style={{
              marginTop: "0.5rem",
              paddingLeft: "0.5rem",
              borderLeft: "2px solid #cbd6e3",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "0.35rem",
              }}
            >
              <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "#687182" }}>
                服装 (Clothing Overlay)
              </span>
              {onAddClothingCompare ? (
                <button
                  aria-label="新增服装 Compare"
                  className="icon-button"
                  onClick={onAddClothingCompare}
                  style={{ height: "24px", minHeight: "24px", width: "24px" }}
                  title="新增服装 Compare"
                  type="button"
                >
                  <Plus size={14} />
                </button>
              ) : null}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              {slot.clothingSlots.map((clothingSlot, index) => (
                <NodeSlot
                  key={clothingSlot.slotId}
                  label={clothingSlot.mode === "compare" ? `服装 (Compare ${index})` : "服装"}
                  placeholder="可选：选择覆盖服装 (默认使用角色原服装)"
                  slot={clothingSlot}
                  onClear={() => {
                    if (onClearClothing) {
                      onClearClothing(clothingSlot.slotId);
                    } else {
                      onSelectClothing?.(null, null);
                    }
                  }}
                  onCreateBlank={() => onCreateBlankClothing?.(clothingSlot.slotId)}
                  onCreateRandom={onCreateRandomClothing ? () => onCreateRandomClothing(clothingSlot.slotId) : undefined}
                  onEdit={(response) => onEditClothing?.(clothingSlot.slotId, response)}
                  onEditRandom={onEditRandomClothing ? () => onEditRandomClothing(clothingSlot.slotId) : undefined}
                  onRemove={
                    clothingSlot.mode === "compare" && onRemoveClothingCompare
                      ? () => onRemoveClothingCompare(clothingSlot.slotId)
                      : undefined
                  }
                  onRestore={() => onRestoreClothing?.(clothingSlot.slotId)}
                  onSelect={(response) => {
                    if (onSelectClothingSlot) {
                      onSelectClothingSlot(clothingSlot.slotId, response);
                    } else {
                      onSelectClothing?.(response.ref, response.node);
                    }
                  }}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="clothing-overlay-picker" style={{ marginTop: "0.5rem", paddingLeft: "0.5rem", borderLeft: "2px solid var(--border-color, #444)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.25rem" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--text-muted, #888)" }}>服装 (Clothing Overlay)</span>
              {slot.clothingRef ? (
                <button
                  className="icon-button"
                  onClick={() => onSelectClothing?.(null, null)}
                  style={{ fontSize: "0.75rem", padding: "0 0.25rem", height: "auto" }}
                  title="清除服装覆盖"
                  type="button"
                >
                  清除
                </button>
              ) : null}
            </div>
            <NodePicker
              label="服装"
              onClear={() => onSelectClothing?.(null, null)}
              onSelect={(node) => void handleSelectClothing(node)}
              placeholder="可选：选择覆盖服装 (默认使用角色原服装)"
              role="clothing"
              value={slot.clothingNode?.name || (slot.clothingRef ? slot.clothingRef.split(/[/\\]/).pop() || slot.clothingRef : "")}
            />
          </div>
        )
      ) : null}
      {loading ? <small className="field-hint">正在读取节点...</small> : null}
      {error ? <small className="field-error">{error}</small> : null}
    </section>
  );
}
