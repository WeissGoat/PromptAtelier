import { Plus } from "lucide-react";

import { nodeSlotStatus } from "../nodes/temporaryNodes";
import type { NodeRole } from "../nodes/types";
import { useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import type { NodeVariantSlot } from "../workspace/types";
import { NodeSlot } from "./NodeSlot";

const labels: Record<NodeRole, string> = { artist: "Artist", character: "Character", action: "Action" };

function isDirty(slot: NodeVariantSlot): boolean {
  const status = nodeSlotStatus(slot);
  return status === "modified" || status === "temporary";
}

export function NodeRoleGroup({ role, onEditSlot }: { role: NodeRole; onEditSlot?: (slotId: string) => void }) {
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
        onEdit={() => onEditSlot ? onEditSlot(slot.slotId) : workspace.openEditor(slot.slotId)}
        onRemove={slot.mode === "compare" ? () => {
          if (isDirty(slot) && !window.confirm("删除后将丢失当前 Compare 临时修改，是否继续？")) return;
          workspace.removeCompare(slot.slotId);
        } : undefined}
        onRestore={() => workspace.restoreSlot(slot.slotId)}
        onSelect={(ref, node) => workspace.selectNode(slot.slotId, ref, node)}
        placeholder={`搜索 ${label} 节点`}
        slot={slot}
      />
    );
  }

  return (
    <section className="node-role-group">
      <div className="node-role-title">
        <h3>{label}</h3>
        <button aria-label={`新增${label} Compare`} className="icon-button" onClick={() => workspace.addCompare(role)} title="新增 Compare" type="button"><Plus size={16} /></button>
      </div>
      {renderSlot(group.primary)}
      {group.compares.map(renderSlot)}
    </section>
  );
}
