import { beforeEach, describe, expect, it } from "vitest";

import { createTemporaryNode } from "../nodes/temporaryNodes";
import {
  CUSTOM_WORKSPACE_SCHEMA,
  CUSTOM_WORKSPACE_STORAGE_KEY,
  createEmptySlot,
  createEmptyWorkspace,
  loadWorkspaceSnapshot,
  saveWorkspaceSnapshot,
} from "./storage";

describe("workspace storage", () => {
  beforeEach(() => localStorage.clear());

  it("round-trips primary, compare and temporary nodes", () => {
    const state = createEmptyWorkspace();
    state.groups.character.primary.draftNode = createTemporaryNode("character", "homura");
    const compare = createEmptySlot("action", "compare");
    compare.draftNode = createTemporaryNode("action", "standing");
    state.groups.action.compares.push(compare);

    saveWorkspaceSnapshot(localStorage, state);
    const loaded = loadWorkspaceSnapshot(localStorage);

    expect(loaded.status).toBe("loaded");
    expect(loaded.state.groups.character.primary.draftNode?.id).toBe("homura");
    expect(loaded.state.groups.action.compares[0].draftNode?.id).toBe("standing");
  });

  it("round-trips per-slot source form drafts", () => {
    const state = createEmptyWorkspace();
    state.groups.artist.primary.draftEditorValues = {
      prompt_prefix: ["official style", "1.7::monochrome"],
    };

    saveWorkspaceSnapshot(localStorage, state);
    const loaded = loadWorkspaceSnapshot(localStorage);

    expect(loaded.status).toBe("loaded");
    expect(loaded.state.groups.artist.primary.draftEditorValues).toEqual({
      prompt_prefix: ["official style", "1.7::monochrome"],
    });
  });

  it("migrates an open legacy editor draft into its node slot", () => {
    const state = createEmptyWorkspace();
    state.groups.artist.primary.sourceRef = "artists/manga";
    state.groups.artist.primary.draftEditorValues = undefined;
    state.editor = {
      slotId: "primary-artist",
      tab: "form",
      draftNode: null,
      baselineNode: null,
      editValues: { prompt_prefix: ["official style", "1.7::monochrome"] },
      baselineValues: { prompt_prefix: ["official style", "::monochrome"] },
    };

    saveWorkspaceSnapshot(localStorage, state);
    const loaded = loadWorkspaceSnapshot(localStorage);

    expect(loaded.status).toBe("loaded");
    expect(loaded.state.groups.artist.primary.draftEditorValues).toEqual({
      prompt_prefix: ["official style", "1.7::monochrome"],
    });
  });

  it("uses an empty negative prompt by default", () => {
    expect(createEmptyWorkspace().params.negative).toBe("");
  });

  it("migrates an old workspace snapshot with prompt behavior defaults", () => {
    const state = createEmptyWorkspace();
    const snapshot = JSON.parse(JSON.stringify(state)) as Record<string, unknown>;
    snapshot.schema = "promptatelier.custom-workspace/v1";
    delete snapshot.promptBehaviorGroup;
    delete snapshot.activePromptBehaviorSlotId;
    localStorage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, JSON.stringify(snapshot));

    const loaded = loadWorkspaceSnapshot(localStorage);

    expect(loaded.status).toBe("loaded");
    expect(loaded.state.schema).toBe(CUSTOM_WORKSPACE_SCHEMA);
    expect(loaded.state.promptBehaviorGroup.primary.value.characterPrompts).toEqual({ mode: "auto", addMaleCaption: true });
    expect(loaded.state.promptBehaviorGroup.primary.value.identityMinimal).toEqual({ mode: "inherit", sections: [] });
    expect(loaded.state.promptBehaviorGroup.primary.value.policyRules).toEqual({});
  });

  it("persists random node configuration without runtime scan results", () => {
    const state = createEmptyWorkspace();
    state.groups.action.primary.sourceKind = "random";
    state.groups.action.primary.randomSpec = {
      source: { type: "collection", value: "foot", recursive: false, include_names: [], exclude_names: [] },
      filters: { classify: { phase: [], species: [], cast: [], domain: ["foot"], subtype: ["sole_focus"], pose: [], environment: [], tone: [], flags: [], clothing: [] } },
    };

    saveWorkspaceSnapshot(localStorage, state);
    const loaded = loadWorkspaceSnapshot(localStorage);

    expect(loaded.status).toBe("loaded");
    expect(loaded.state.groups.action.primary.sourceKind).toBe("random");
    expect(loaded.state.groups.action.primary.randomSpec?.filters.classify.subtype).toEqual(["sole_focus"]);
  });

  it("migrates v1 prompt behavior into the primary behavior variant", () => {
    const state = createEmptyWorkspace();
    const snapshot = JSON.parse(JSON.stringify(state)) as Record<string, unknown>;
    snapshot.schema = "promptatelier.custom-workspace/v1";
    snapshot.promptBehavior = {
      identityMinimal: { mode: "override", sections: ["character"] },
      characterPrompts: { mode: "off", addMaleCaption: false },
      policyRules: { visibility_policy: { state: "disabled" } },
    };
    delete snapshot.promptBehaviorGroup;
    delete snapshot.activePromptBehaviorSlotId;
    localStorage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, JSON.stringify(snapshot));

    const loaded = loadWorkspaceSnapshot(localStorage);

    expect(loaded.status).toBe("loaded");
    expect(loaded.state.promptBehaviorGroup.primary.value).toEqual(snapshot.promptBehavior);
    expect(loaded.state.promptBehaviorGroup.compares).toEqual([]);
    expect(loaded.state.activePromptBehaviorSlotId).toBe("primary-prompt-behavior");
  });

  it("round-trips prompt behavior variants and the active slot", () => {
    const state = createEmptyWorkspace();
    state.promptBehaviorGroup.compares.push({
      slotId: "behavior-off",
      label: "No Character Prompts",
      mode: "compare",
      value: {
        ...state.promptBehaviorGroup.primary.value,
        characterPrompts: { mode: "off", addMaleCaption: false },
      },
    });
    state.activePromptBehaviorSlotId = "behavior-off";

    saveWorkspaceSnapshot(localStorage, state);
    const loaded = loadWorkspaceSnapshot(localStorage);

    expect(loaded.status).toBe("loaded");
    expect(loaded.state.promptBehaviorGroup.compares[0].label).toBe("No Character Prompts");
    expect(loaded.state.promptBehaviorGroup.compares[0].value.characterPrompts.mode).toBe("off");
    expect(loaded.state.activePromptBehaviorSlotId).toBe("behavior-off");
  });

  it("rejects malformed JSON without deleting the stored value", () => {
    localStorage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, "{broken");
    const loaded = loadWorkspaceSnapshot(localStorage);
    expect(loaded.status).toBe("invalid");
    expect(localStorage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY)).toBe("{broken");
  });

  it("rejects a snapshot with a different schema", () => {
    localStorage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, JSON.stringify({ schema: "v0" }));
    expect(loadWorkspaceSnapshot(localStorage).status).toBe("invalid");
  });

  it("persists only workspace input fields", () => {
    const state = createEmptyWorkspace() as typeof createEmptyWorkspace extends () => infer T ? T & { jobs?: unknown } : never;
    state.jobs = [{ id: "runtime-job" }];
    saveWorkspaceSnapshot(localStorage, state);
    expect(JSON.parse(localStorage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY) ?? "{}").jobs).toBeUndefined();
  });
});
