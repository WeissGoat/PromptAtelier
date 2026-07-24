import type {
  PromptBehaviorGroup,
  PromptBehaviorParams,
  PromptBehaviorVariant,
  SlotMode,
} from "./types";

export const PRIMARY_PROMPT_BEHAVIOR_SLOT_ID = "primary-prompt-behavior";

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function createDefaultPromptBehavior(): PromptBehaviorParams {
  return {
    identityMinimal: { mode: "inherit", sections: [] },
    characterPrompts: { mode: "auto", addMaleCaption: true },
    policyRules: {},
  };
}

export function createDefaultPromptBehaviorGroup(): PromptBehaviorGroup {
  return {
    primary: {
      slotId: PRIMARY_PROMPT_BEHAVIOR_SLOT_ID,
      label: "Default",
      mode: "primary",
      value: createDefaultPromptBehavior(),
    },
    compares: [],
  };
}

export function promptBehaviorVariants(group: PromptBehaviorGroup): PromptBehaviorVariant[] {
  return [group.primary, ...group.compares];
}

export function findPromptBehaviorVariant(
  group: PromptBehaviorGroup,
  slotId: string,
): PromptBehaviorVariant | null {
  return promptBehaviorVariants(group).find((variant) => variant.slotId === slotId) ?? null;
}

export function normalizePromptBehavior(value: unknown): PromptBehaviorParams {
  if (!isObject(value)) return createDefaultPromptBehavior();

  const identity = isObject(value.identityMinimal) ? value.identityMinimal : {};
  const identityMode = identity.mode === "override" ? "override" : "inherit";
  const identitySections = Array.isArray(identity.sections)
    ? [...new Set(identity.sections.map((item) => String(item).trim()).filter(Boolean))]
    : [];

  const character = isObject(value.characterPrompts) ? value.characterPrompts : {};
  const characterMode = character.mode === "off" ? "off" : "auto";
  const addMaleCaption = typeof character.addMaleCaption === "boolean"
    ? character.addMaleCaption
    : true;

  const policyRules: PromptBehaviorParams["policyRules"] = {};
  if (isObject(value.policyRules)) {
    for (const [ruleId, rawRule] of Object.entries(value.policyRules)) {
      if (!isObject(rawRule)) continue;
      if (rawRule.state !== "inherit" && rawRule.state !== "enabled" && rawRule.state !== "disabled") continue;
      const options = isObject(rawRule.options) ? structuredClone(rawRule.options) : undefined;
      policyRules[ruleId] = options ? { state: rawRule.state, options } : { state: rawRule.state };
    }
  }

  return {
    identityMinimal: { mode: identityMode, sections: identitySections },
    characterPrompts: { mode: characterMode, addMaleCaption },
    policyRules,
  };
}

function normalizeVariant(
  value: unknown,
  mode: SlotMode,
  fallbackSlotId: string,
  fallbackLabel: string,
): PromptBehaviorVariant {
  const raw = isObject(value) ? value : {};
  const slotId = typeof raw.slotId === "string" && raw.slotId.trim()
    ? raw.slotId.trim()
    : fallbackSlotId;
  const label = typeof raw.label === "string" && raw.label.trim()
    ? raw.label.trim()
    : fallbackLabel;
  return {
    slotId,
    label,
    mode,
    value: normalizePromptBehavior(raw.value),
  };
}

export function normalizePromptBehaviorGroup(value: unknown): PromptBehaviorGroup {
  if (!isObject(value)) return createDefaultPromptBehaviorGroup();
  const primary = normalizeVariant(
    value.primary,
    "primary",
    PRIMARY_PROMPT_BEHAVIOR_SLOT_ID,
    "Default",
  );
  const seen = new Set([primary.slotId]);
  const compares: PromptBehaviorVariant[] = [];
  if (Array.isArray(value.compares)) {
    for (const [index, rawVariant] of value.compares.entries()) {
      if (!isObject(rawVariant) || typeof rawVariant.slotId !== "string" || !rawVariant.slotId.trim()) continue;
      const variant = normalizeVariant(
        rawVariant,
        "compare",
        `compare-prompt-behavior-${index + 1}`,
        `Compare ${index + 1}`,
      );
      if (seen.has(variant.slotId)) continue;
      seen.add(variant.slotId);
      compares.push(variant);
    }
  }
  return { primary, compares };
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (isObject(value)) {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, sortKeys(entry)]),
    );
  }
  return value;
}

export function promptBehaviorFingerprint(value: PromptBehaviorParams): string {
  const canonical = JSON.stringify(sortKeys(value));
  let hash = 0x811c9dc5;
  for (let index = 0; index < canonical.length; index += 1) {
    hash ^= canonical.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `fnv1a:${(hash >>> 0).toString(16).padStart(8, "0")}`;
}
