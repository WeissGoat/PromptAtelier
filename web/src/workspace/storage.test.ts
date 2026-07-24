import { beforeEach, describe, expect, it } from "vitest";

import { createTemporaryNode } from "../nodes/temporaryNodes";
import {
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
    delete snapshot.promptBehavior;
    localStorage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, JSON.stringify(snapshot));

    const loaded = loadWorkspaceSnapshot(localStorage);

    expect(loaded.status).toBe("loaded");
    expect(loaded.state.promptBehavior.characterPrompts).toEqual({ mode: "auto", addMaleCaption: true });
    expect(loaded.state.promptBehavior.identityMinimal).toEqual({ mode: "inherit", sections: [] });
    expect(loaded.state.promptBehavior.policyRules).toEqual({});
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
