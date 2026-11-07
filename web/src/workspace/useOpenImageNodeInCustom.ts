import { useCallback } from "react";

import { apiGet } from "../api/client";
import type { NodeReadResponse } from "../api/types";
import type { NodeRole } from "../nodes/types";
import { useCustomWorkspace } from "./CustomWorkspaceProvider";
import type { CustomWorkspaceState, NodeVariantSlot } from "./types";

export type ImageNodeOpenTarget = {
  role: string;
  name?: string | null;
  ref: string | null;
  slotId?: string | null;
  random?: boolean;
};

export type OpenImageNodeInCustom = (target: ImageNodeOpenTarget) => Promise<void>;

const nodeRoles = new Set<NodeRole>(["artist", "character", "action", "clothing"]);

function normalizedRef(value: string | null | undefined): string {
  return (value ?? "").trim().replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

function sameRef(left: string | null | undefined, right: string | null | undefined): boolean {
  const normalized = normalizedRef(left);
  return Boolean(normalized) && normalized === normalizedRef(right);
}

function findFixedNodeSlot(
  state: CustomWorkspaceState,
  role: NodeRole,
  ref: string,
): NodeVariantSlot | null {
  function matches(slot: NodeVariantSlot): boolean {
    return slot.role === role
      && slot.sourceKind !== "random"
      && sameRef(slot.sourceRef, ref);
  }

  for (const group of Object.values(state.groups)) {
    if (matches(group.primary)) return group.primary;
    for (const clothing of group.primary.clothingSlots ?? []) {
      if (matches(clothing)) return clothing;
    }
    for (const compare of group.compares) {
      if (matches(compare)) return compare;
      for (const clothing of compare.clothingSlots ?? []) {
        if (matches(clothing)) return clothing;
      }
    }
  }
  return null;
}

async function readNode(role: NodeRole, ref: string): Promise<NodeReadResponse> {
  return apiGet<NodeReadResponse>(
    `/nodes/read?${new URLSearchParams({ ref, role }).toString()}`,
  );
}

/** 把图片元数据里的节点定位到 Custom：优先打开已有槽位/随机组成员，找不到时新增 Compare。 */
export function useOpenImageNodeInCustom(onOpenCustom?: () => void): OpenImageNodeInCustom {
  const workspace = useCustomWorkspace();

  return useCallback(async (target) => {
    const role = target.role.trim().toLowerCase() as NodeRole;
    if (!nodeRoles.has(role)) {
      throw new Error(`暂不支持在 Custom 中打开 ${target.role || "未知角色"} 节点。`);
    }
    const ref = target.ref?.trim();
    if (!ref) throw new Error("这个节点没有可读取的 ref。");

    const openRandomMember = (slot: NodeVariantSlot, response?: NodeReadResponse) => {
      const name = response?.node.name
        || target.name?.trim()
        || response?.node.id
        || ref.split(/[/\\]/).pop()
        || ref;
      workspace.openMemberEditor(slot.slotId, ref, name, response);
    };
    const navigate = () => {
      if (onOpenCustom) onOpenCustom();
      else if (typeof window !== "undefined") window.location.hash = "#/custom";
    };

    const requestedSlot = target.slotId ? workspace.findSlot(target.slotId) : null;
    if (
      target.random
      && requestedSlot?.sourceKind === "random"
      && requestedSlot.role === role
    ) {
      if (requestedSlot.memberDrafts?.[ref]) openRandomMember(requestedSlot);
      else openRandomMember(requestedSlot, await readNode(role, ref));
      navigate();
      return;
    }

    const existingSlot = findFixedNodeSlot(workspace.state, role, ref);
    if (existingSlot) {
      workspace.openEditor(existingSlot.slotId);
      navigate();
      return;
    }

    const response = await readNode(role, ref);
    const fallbackSlotId = role === "clothing"
      ? workspace.addClothingCompare(workspace.state.groups.character.primary.slotId)
      : workspace.addCompare(role);
    workspace.openEditor(fallbackSlotId, response);
    navigate();
  }, [onOpenCustom, workspace]);
}
