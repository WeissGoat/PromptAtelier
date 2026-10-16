import { Plus } from "lucide-react";

import type { NodeReadResponse } from "../api/types";
import { nodeSlotStatus } from "../nodes/temporaryNodes";
import type { GroupRole } from "../nodes/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import type { NodeVariantSlot } from "../workspace/types";
import { NodeSlot } from "./NodeSlot";

const labels: Record<GroupRole, string> = { artist: "Artist", character: "Character", action: "Action" };
const titles: Record<GroupRole, string> = { artist: "画风", character: "角色", action: "动作" };

function isDirty(slot: NodeVariantSlot): boolean {
  const status = nodeSlotStatus(slot);
  return status === "modified" || status === "temporary";
}

export function NodeRoleGroup({ role, onEditSlot }: { role: GroupRole; onEditSlot?: (slotId: string, response?: NodeReadResponse) => void }) {
  const workspace = useCustomWorkspace();
  const group = workspace.state.groups[role];
  const label = labels[role];

  function renderSlot(slot: NodeVariantSlot) {
    return (
      <NodeSlot
        key={slot.slotId}
        label={label}
        onClear={() => workspace.clearSlot(slot.slotId)}
        onCreateBlank={() => workspace.createBlank(slot.slotId)}
        onCreateRandom={() => workspace.createRandom(slot.slotId)}
        onEdit={(response) => onEditSlot ? onEditSlot(slot.slotId, response) : workspace.openEditor(slot.slotId, response)}
        onEditRandom={() => workspace.openRandomEditor(slot.slotId)}
        onRemove={slot.mode === "compare" ? () => {
          if (isDirty(slot) && !window.confirm("删除后将丢失当前 Compare 临时修改，是否继续？")) return;
          workspace.removeCompare(slot.slotId);
        } : undefined}
        onRestore={() => workspace.restoreSlot(slot.slotId)}
        onSelect={(response) => workspace.selectNode(slot.slotId, response.ref, response.node, response.editor)}
        onSelectClothing={(clothingRef, clothingNode) => workspace.setClothingForSlot(slot.slotId, clothingRef, clothingNode)}
        onAddClothingCompare={role === "character" ? () => workspace.addClothingCompare(slot.slotId) : undefined}
        onRemoveClothingCompare={role === "character" ? (clothingSlotId) => workspace.removeClothingCompare(slot.slotId, clothingSlotId) : undefined}
        onSelectClothingSlot={role === "character" ? (clothingSlotId, response) => workspace.selectNode(clothingSlotId, response.ref, response.node, response.editor) : undefined}
        onCreateBlankClothing={role === "character" ? (clothingSlotId) => workspace.createBlank(clothingSlotId) : undefined}
        onCreateRandomClothing={role === "character" ? (clothingSlotId) => workspace.createRandom(clothingSlotId) : undefined}
        onRestoreClothing={role === "character" ? (clothingSlotId) => workspace.restoreSlot(clothingSlotId) : undefined}
        onClearClothing={role === "character" ? (clothingSlotId) => workspace.clearSlot(clothingSlotId) : undefined}
        onEditClothing={role === "character" ? (clothingSlotId, response) => onEditSlot ? onEditSlot(clothingSlotId, response) : workspace.openEditor(clothingSlotId, response) : undefined}
        onEditRandomClothing={role === "character" ? (clothingSlotId) => workspace.openRandomEditor(clothingSlotId) : undefined}
        placeholder={`搜索 ${label} 节点`}
        slot={slot}
      />
    );
  }

  const variants = 1 + group.compares.length;
  return (
    <section className={`node-role-group role-${role}`}>
      <div className="node-role-title">
        <h3>
          <span className="role-dot" aria-hidden="true" />
          {titles[role]}
          <small>{label}</small>
          {variants > 1 ? <span className="chip violet">{variants} 个对比</span> : null}
        </h3>
        <button aria-label={`新增${label} Compare`} className="btn-sm btn-ghost" onClick={() => workspace.addCompare(role)} title="新增 Compare：同一位置放多个节点做对比" type="button"><Plus size={14} /> Compare</button>
      </div>
      {renderSlot(group.primary)}
      {group.compares.map(renderSlot)}
    </section>
  );
}
