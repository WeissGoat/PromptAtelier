import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createTemporaryNode } from "../nodes/temporaryNodes";
import { CustomWorkspaceProvider, useCustomWorkspace } from "./CustomWorkspaceProvider";
import { CUSTOM_WORKSPACE_STORAGE_KEY } from "./storage";

const artistNode = {
  schema: "tags-machine-core.node/v1" as const,
  kind: "artist" as const,
  id: "artist-a",
  name: "Artist A",
  prompt: { positive: [], negative: [] },
  renderers: { novelai: { params: { steps: 23 } } },
};

function Probe() {
  const workspace = useCustomWorkspace();
  return (
    <div>
      <span data-testid="negative">{workspace.state.params.negative}</span>
      <span data-testid="compares">{workspace.state.groups.artist.compares.length}</span>
      <span data-testid="character">{workspace.state.groups.character.primary.draftNode?.id ?? "empty"}</span>
      <span data-testid="primary-artist">{workspace.state.groups.artist.primary.draftNode?.name ?? "empty"}</span>
      <span data-testid="compare-artist">{workspace.state.groups.artist.compares[0]?.draftNode?.name ?? "empty"}</span>
      <span data-testid="behavior-count">{workspace.state.promptBehaviorGroup.compares.length}</span>
      <span data-testid="active-behavior">{workspace.state.activePromptBehaviorSlotId}</span>
      <span data-testid="primary-behavior-mode">{workspace.state.promptBehaviorGroup.primary.value.characterPrompts.mode}</span>
      <span data-testid="compare-behavior-mode">{workspace.state.promptBehaviorGroup.compares[0]?.value.characterPrompts.mode ?? "empty"}</span>
      <span data-testid="compare-behavior-label">{workspace.state.promptBehaviorGroup.compares[0]?.label ?? "empty"}</span>
      <span data-testid="warning">{workspace.storageWarning}</span>
      <button onClick={() => workspace.addCompare("artist")}>add</button>
      <button onClick={() => workspace.selectNode("primary-artist", "artists/a", artistNode)}>select artist</button>
      <button onClick={() => {
        const compare = workspace.state.groups.artist.compares[0];
        if (compare?.draftNode) workspace.updateDraft(compare.slotId, { ...compare.draftNode, name: "Compare Artist" });
      }}>edit compare artist</button>
      <button onClick={() => workspace.createBlank("primary-character")}>blank</button>
      <button onClick={() => workspace.updateDraft("primary-character", createTemporaryNode("character", "edited"))}>edit</button>
      <button onClick={() => workspace.setParams({ negative: "bad anatomy" })}>negative</button>
      <button onClick={() => workspace.addPromptBehaviorCompare()}>add behavior</button>
      <button onClick={() => workspace.setPromptBehavior({
        ...workspace.state.promptBehaviorGroup.primary.value,
        characterPrompts: { mode: "off", addMaleCaption: false },
      })}>edit behavior</button>
      <button onClick={() => {
        const compare = workspace.state.promptBehaviorGroup.compares[0];
        if (compare) workspace.renamePromptBehavior(compare.slotId, "No Character Prompts");
      }}>rename behavior</button>
      <button onClick={() => {
        const compare = workspace.state.promptBehaviorGroup.compares[0];
        if (compare) workspace.removePromptBehaviorCompare(compare.slotId);
      }}>remove behavior</button>
      <button onClick={workspace.resetWorkspace}>reset</button>
    </div>
  );
}

describe("CustomWorkspaceProvider", () => {
  beforeEach(() => localStorage.clear());
  afterEach(cleanup);

  it("keeps workspace state while children rerender", () => {
    const view = render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("add"));
    fireEvent.click(screen.getByText("blank"));
    view.rerender(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    expect(screen.getByTestId("compares").textContent).toBe("1");
    expect(screen.getByTestId("character").textContent).toBe("temporary-character");
  });

  it("mirrors the primary node into a new compare slot without sharing draft state", () => {
    render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("select artist"));
    fireEvent.click(screen.getByText("add"));

    expect(screen.getByTestId("primary-artist").textContent).toBe("Artist A");
    expect(screen.getByTestId("compare-artist").textContent).toBe("Artist A");

    fireEvent.click(screen.getByText("edit compare artist"));
    expect(screen.getByTestId("primary-artist").textContent).toBe("Artist A");
    expect(screen.getByTestId("compare-artist").textContent).toBe("Compare Artist");
  });

  it("persists workspace changes after the debounce", async () => {
    render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("negative"));
    await waitFor(() => expect(localStorage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY)).toContain("bad anatomy"), { timeout: 1_000 });
  });

  it("mirrors primary prompt behavior without sharing compare state", () => {
    render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("add behavior"));

    expect(screen.getByTestId("behavior-count").textContent).toBe("1");
    expect(screen.getByTestId("active-behavior").textContent).not.toBe("primary-prompt-behavior");
    expect(screen.getByTestId("primary-behavior-mode").textContent).toBe("auto");
    expect(screen.getByTestId("compare-behavior-mode").textContent).toBe("auto");

    fireEvent.click(screen.getByText("edit behavior"));
    expect(screen.getByTestId("primary-behavior-mode").textContent).toBe("auto");
    expect(screen.getByTestId("compare-behavior-mode").textContent).toBe("off");
  });

  it("renames and removes an active prompt behavior compare", () => {
    render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("add behavior"));
    fireEvent.click(screen.getByText("rename behavior"));
    expect(screen.getByTestId("compare-behavior-label").textContent).toBe("No Character Prompts");

    fireEvent.click(screen.getByText("remove behavior"));
    expect(screen.getByTestId("behavior-count").textContent).toBe("0");
    expect(screen.getByTestId("active-behavior").textContent).toBe("primary-prompt-behavior");
  });

  it("persists prompt behavior compare changes after remount", async () => {
    const first = render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("add behavior"));
    fireEvent.click(screen.getByText("edit behavior"));
    fireEvent.click(screen.getByText("rename behavior"));
    await waitFor(() => expect(localStorage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY)).toContain("No Character Prompts"), { timeout: 1_000 });
    first.unmount();

    render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    expect(screen.getByTestId("compare-behavior-mode").textContent).toBe("off");
    expect(screen.getByTestId("compare-behavior-label").textContent).toBe("No Character Prompts");
  });

  it("restores a saved workspace on remount", async () => {
    const first = render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("edit"));
    await waitFor(() => expect(localStorage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY)).toContain("edited"), { timeout: 1_000 });
    first.unmount();
    render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    expect(screen.getByTestId("character").textContent).toBe("edited");
  });

  it("does not overwrite invalid storage until reset", async () => {
    localStorage.setItem(CUSTOM_WORKSPACE_STORAGE_KEY, "{broken");
    render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("negative"));
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    expect(localStorage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY)).toBe("{broken");
    expect(screen.getByTestId("warning").textContent).not.toBe("");
    fireEvent.click(screen.getByText("reset"));
    expect(localStorage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY)).toBeNull();
  });
});
