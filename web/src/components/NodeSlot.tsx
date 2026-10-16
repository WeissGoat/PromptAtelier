import { ChevronDown, FilePlus2, Layers, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { apiGet, errorMessage } from "../api/client";
import type { NodeReadResponse, NodeSummary } from "../api/types";
import { nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeDocument } from "../nodes/types";
import type { NodeVariantSlot } from "../workspace/types";
import { GroupMembers, memberEdited } from "./GroupMembers";
import { NodeGroupSummary } from "./NodeGroupSummary";
import { NodePicker } from "./NodePicker";
import { NodePreviewImage } from "./NodePreviewImage";

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
  if (status === "random") return "节点组";
  return "未选择";
}

function requiresConfirmation(slot: NodeVariantSlot): boolean {
  const status = nodeSlotStatus(slot);
  return status === "modified" || status === "temporary";
}

function displayName(slot: NodeVariantSlot): string {
  if (slot.sourceKind === "random") {
    const source = slot.randomSpec?.source;
    const mode = slot.randomSpec?.drawMode === "sequential" ? "顺序" : "随机";
    return source?.value ? `节点组 · ${mode} · ${source.value}` : `节点组 · ${mode} · 未配置来源`;
  }
  const name = slot.draftNode?.name || slot.sourceNode?.name || slot.draftNode?.id || "";
  const status = nodeSlotStatus(slot);
  return name && (status === "modified" || status === "temporary") ? `${name} *` : name;
}

/** 路径只留最后两级，完整路径放在 title 里。 */
function shortPath(ref: string): string {
  const parts = ref.split(/[/\\]/).filter(Boolean);
  return parts.slice(-2).join(" / ");
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
  const [membersOpen, setMembersOpen] = useState(false);
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

  const isGroup = slot.sourceKind === "random";
  const status = nodeSlotStatus(slot);
  const memberCount = Object.keys(slot.memberDrafts ?? {}).filter((ref) => memberEdited(slot, ref)).length;

  return (
    <section className={`node-slot slot-card${slot.mode === "compare" ? " compare-node-slot" : ""}${isGroup ? " is-group" : ""}`}>
      <div className="node-slot-header">
        <div aria-label={`${label}节点来源`} className="slot-mode" role="group">
          <button
            aria-pressed={!isGroup}
            className={!isGroup ? "active" : ""}
            onClick={() => {
              if (isGroup) runReplacingAction(onClear, "切换成单个节点会清掉当前节点组设置，是否继续？");
            }}
            title="选一个固定节点"
            type="button"
          >
            单个
          </button>
          {onCreateRandom ? (
            <button
              aria-label={`创建${label}节点组`}
              aria-pressed={isGroup}
              className={isGroup ? "active" : ""}
              onClick={() => {
                if (isGroup) onEditRandom?.();
                else runReplacingAction(onCreateRandom, "当前节点将被替换为节点组，是否继续？");
              }}
              title="节点组：一组节点随机或按顺序抽取"
              type="button"
            >
              <Layers size={13} /> 节点组
            </button>
          ) : null}
        </div>
        <div className="node-slot-labels">
          {slot.mode === "compare" ? <span className="compare-badge chip violet">Compare</span> : null}
          {!isGroup ? <span className={`node-status chip${status === "modified" ? " accent" : status === "temporary" ? " warning" : ""}`}>{statusLabel(slot)}</span> : null}
        </div>
        <div className="node-slot-actions">
          <button aria-label={`编辑${label}节点`} className="icon-button btn-ghost" disabled={(!slot.draftNode && !isGroup) || loading} onClick={() => void handleEdit()} title={isGroup ? "节点组设置" : "编辑节点"} type="button"><Pencil size={15} /></button>
          {!isGroup ? <button aria-label={`新建空白${label}节点`} className="icon-button btn-ghost" onClick={() => runReplacingAction(onCreateBlank, "当前临时修改将被替换，是否继续？")} title="新建空白临时节点" type="button"><FilePlus2 size={15} /></button> : null}
          {!isGroup ? <button aria-label={`还原${label}节点`} className="icon-button btn-ghost" disabled={!slot.sourceNode || status === "original"} onClick={() => runReplacingAction(onRestore, "当前临时修改将被还原，是否继续？")} title="还原原始节点" type="button"><RotateCcw size={15} /></button> : null}
          {onRemove ? (
            <button aria-label={`删除${label} Compare节点`} className="icon-button btn-ghost btn-danger" onClick={onRemove} title="删除 Compare 节点" type="button"><Trash2 size={15} /></button>
          ) : null}
        </div>
      </div>
      {isGroup ? (
        <div className="slot-group">
          <NodeGroupSummary onOpen={onEditRandom} slot={slot} />
          {slot.randomSpec?.source.value.trim() ? (
            <>
              <button
                aria-expanded={membersOpen}
                className="slot-group-toggle btn-sm btn-ghost"
                onClick={() => setMembersOpen((open) => !open)}
                type="button"
              >
                <ChevronDown className={membersOpen ? "chevron open" : "chevron"} size={14} />
                {membersOpen ? "收起成员" : "展开成员"}
                {memberCount ? <span className="chip accent">{memberCount} 个改过</span> : null}
              </button>
              {membersOpen ? <GroupMembers slot={slot} variant="list" /> : null}
            </>
          ) : null}
        </div>
      ) : (
        <>
          <NodePicker
            label={label}
            onClear={() => runReplacingAction(onClear, "当前临时修改将被清除，是否继续？")}
            onSelect={(node) => void handleSelect(node)}
            placeholder={placeholder}
            role={slot.role}
            value={displayName(slot)}
          />
          {slot.sourceRef ? (
            <div className="slot-node-card">
              <NodePreviewImage className="node-slot-preview" name={displayName(slot) || slot.sourceRef} nodeRef={slot.sourceRef} size={240} />
              <div className="slot-node-meta">
                <span className="slot-node-name">{displayName(slot)}</span>
                <span className="slot-node-path" title={slot.sourceRef}>{shortPath(slot.sourceRef)}</span>
              </div>
            </div>
          ) : slot.draftNode ? (
            <div className="slot-node-card temporary">
              <span className="slot-node-meta">
                <span className="slot-node-name">{displayName(slot)}</span>
                <span className="slot-node-path">还没有源文件，只用于这次出图</span>
              </span>
            </div>
          ) : null}
        </>
      )}
      {slot.role === "character" ? (
        slot.clothingSlots && slot.clothingSlots.length > 0 ? (
          <div className="clothing-overlay-group">
            <div className="clothing-overlay-head">
              <span>服装覆盖 <small>不选就用角色自带服装</small></span>
              {onAddClothingCompare ? (
                <button aria-label="新增服装 Compare" className="icon-button btn-ghost btn-sm" onClick={onAddClothingCompare} title="新增服装 Compare" type="button"><Plus size={14} /></button>
              ) : null}
            </div>
            <div className="clothing-overlay-list">
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
          <div className="clothing-overlay-group">
            <div className="clothing-overlay-head">
              <span>服装覆盖 <small>不选就用角色自带服装</small></span>
              {slot.clothingRef ? (
                <button className="btn-sm btn-ghost" onClick={() => onSelectClothing?.(null, null)} title="清除服装覆盖" type="button">清除</button>
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
