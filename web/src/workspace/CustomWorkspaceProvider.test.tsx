import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createTemporaryNode } from "../nodes/temporaryNodes";
import { CustomWorkspaceProvider, useCustomWorkspace } from "./CustomWorkspaceProvider";
import { CUSTOM_WORKSPACE_STORAGE_KEY } from "./storage";

function Probe() {
  const workspace = useCustomWorkspace();
  return (
    <div>
      <span data-testid="negative">{workspace.state.params.negative}</span>
      <span data-testid="compares">{workspace.state.groups.artist.compares.length}</span>
      <span data-testid="character">{workspace.state.groups.character.primary.draftNode?.id ?? "empty"}</span>
      <span data-testid="warning">{workspace.storageWarning}</span>
      <button onClick={() => workspace.addCompare("artist")}>add</button>
      <button onClick={() => workspace.createBlank("primary-character")}>blank</button>
      <button onClick={() => workspace.updateDraft("primary-character", createTemporaryNode("character", "edited"))}>edit</button>
      <button onClick={() => workspace.setParams({ negative: "bad anatomy" })}>negative</button>
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

  it("persists workspace changes after the debounce", async () => {
    render(<CustomWorkspaceProvider><Probe /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("negative"));
    await waitFor(() => expect(localStorage.getItem(CUSTOM_WORKSPACE_STORAGE_KEY)).toContain("bad anatomy"), { timeout: 1_000 });
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
