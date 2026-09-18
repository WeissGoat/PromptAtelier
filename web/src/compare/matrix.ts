import type { GroupRole, NodeRole } from "../nodes/types";
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
  clothing?: NodeVariantSlot | null;
  promptBehavior: PromptBehaviorVariant;
};

export type CompareDimensions = Record<NodeRole, number> & { behavior: number };

export function selectedSlots(group: RoleNodeGroup): NodeVariantSlot[] {
  return [group.primary, ...group.compares].filter((slot) => (
    slot.sourceKind === "random" ? Boolean(slot.randomSpec?.source.value.trim()) : Boolean(slot.draftNode)
  ));
}

export function activeClothingSlots(slot: NodeVariantSlot | null): NodeVariantSlot[] {
  if (!slot || slot.role !== "character" || !slot.clothingSlots) return [];
  return slot.clothingSlots.filter((cs) => (
    cs.sourceKind === "random" ? Boolean(cs.randomSpec?.source.value.trim()) : Boolean(cs.draftNode)
  ));
}

export type CharacterClothingPair = {
  character: NodeVariantSlot | null;
  clothing: NodeVariantSlot | null;
};

export function characterFactors(group: RoleNodeGroup): CharacterClothingPair[] {
  const selectedCharacters = selectedSlots(group);
  if (!selectedCharacters.length) {
    return [{ character: null, clothing: null }];
  }
  const pairs: CharacterClothingPair[] = [];
  for (const character of selectedCharacters) {
    const clothings = activeClothingSlots(character);
    if (clothings.length === 0) {
      pairs.push({ character, clothing: null });
    } else {
      for (const clothing of clothings) {
        pairs.push({ character, clothing });
      }
    }
  }
  return pairs;
}

function factor(group: RoleNodeGroup): Array<NodeVariantSlot | null> {
  const selected = selectedSlots(group);
  return selected.length ? selected : [null];
}

export function compareDimensions(
  groups: Record<GroupRole, RoleNodeGroup>,
  promptBehaviorGroup: PromptBehaviorGroup,
): CompareDimensions {
  const charPairs = characterFactors(groups.character);
  return {
    artist: selectedSlots(groups.artist).length || 1,
    character: charPairs.length,
    action: selectedSlots(groups.action).length || 1,
    clothing: 1,
    behavior: promptBehaviorVariants(promptBehaviorGroup).length,
  };
}

export function compareCount(
  groups: Record<GroupRole, RoleNodeGroup>,
  promptBehaviorGroup: PromptBehaviorGroup,
): number {
  const dimensions = compareDimensions(groups, promptBehaviorGroup);
  return dimensions.artist * dimensions.character * dimensions.action * dimensions.behavior;
}

export function buildCompareMatrix(
  groups: Record<GroupRole, RoleNodeGroup>,
  promptBehaviorGroup: PromptBehaviorGroup,
): CompareCombination[] {
  const combinations: CompareCombination[] = [];
  for (const artist of factor(groups.artist)) {
    for (const { character, clothing } of characterFactors(groups.character)) {
      for (const action of factor(groups.action)) {
        for (const promptBehavior of promptBehaviorVariants(promptBehaviorGroup)) {
          combinations.push({
            combinationId: [
              artist?.slotId ?? "artist-null",
              character?.slotId ?? "character-null",
              ...(clothing ? [clothing.slotId] : []),
              action?.slotId ?? "action-null",
              promptBehavior.slotId,
            ].join("::"),
            artist,
            character,
            action,
            clothing,
            promptBehavior,
          });
        }
      }
    }
  }
  return combinations;
}
