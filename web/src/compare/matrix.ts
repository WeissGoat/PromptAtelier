import type { NodeRole } from "../nodes/types";
import { promptBehaviorVariants } from "../workspace/promptBehavior";
import type {
  NodeVariantSlot,
  PromptBehaviorGroup,
  PromptBehaviorVariant,
  RoleNodeGroup,
} from "../workspace/types";

export type CompareCombination = {
  combinationId: string;
  artist: NodeVariantSlot | null;
  character: NodeVariantSlot | null;
  action: NodeVariantSlot | null;
  promptBehavior: PromptBehaviorVariant;
};

export type CompareDimensions = Record<NodeRole, number> & { behavior: number };

export function selectedSlots(group: RoleNodeGroup): NodeVariantSlot[] {
  return [group.primary, ...group.compares].filter((slot) => Boolean(slot.draftNode));
}

function factor(group: RoleNodeGroup): Array<NodeVariantSlot | null> {
  const selected = selectedSlots(group);
  return selected.length ? selected : [null];
}

export function compareDimensions(
  groups: Record<NodeRole, RoleNodeGroup>,
  promptBehaviorGroup: PromptBehaviorGroup,
): CompareDimensions {
  return {
    artist: selectedSlots(groups.artist).length || 1,
    character: selectedSlots(groups.character).length || 1,
    action: selectedSlots(groups.action).length || 1,
    behavior: promptBehaviorVariants(promptBehaviorGroup).length,
  };
}

export function compareCount(
  groups: Record<NodeRole, RoleNodeGroup>,
  promptBehaviorGroup: PromptBehaviorGroup,
): number {
  const dimensions = compareDimensions(groups, promptBehaviorGroup);
  return dimensions.artist * dimensions.character * dimensions.action * dimensions.behavior;
}

export function buildCompareMatrix(
  groups: Record<NodeRole, RoleNodeGroup>,
  promptBehaviorGroup: PromptBehaviorGroup,
): CompareCombination[] {
  const combinations: CompareCombination[] = [];
  for (const artist of factor(groups.artist)) {
    for (const character of factor(groups.character)) {
      for (const action of factor(groups.action)) {
        for (const promptBehavior of promptBehaviorVariants(promptBehaviorGroup)) {
          combinations.push({
            combinationId: [
              artist?.slotId ?? "artist-null",
              character?.slotId ?? "character-null",
              action?.slotId ?? "action-null",
              promptBehavior.slotId,
            ].join("::"),
            artist,
            character,
            action,
            promptBehavior,
          });
        }
      }
    }
  }
  return combinations;
}
