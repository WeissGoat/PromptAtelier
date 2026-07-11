import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeDocument } from "../nodes/types";
import { CustomWorkspaceProvider, useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { NodeWorkspaceEditor } from "./NodeWorkspaceEditor";

const node: NodeDocument = {
  schema: "tags-machine-core.node/v1",
  kind: "character",
  id: "homura",
  name: "Homura",
  description: "source",
  prompt: { positive: [{ text: "akemi_homura" }], negative: [] },
  tags: { hair: ["black_hair"] },
  legacy: { source_file: "old.txt", keep: true },
};

function Harness() {
  const workspace = useCustomWorkspace();
  const slot = workspace.state.groups.character.primary;
  return (
    <>
      <button onClick={() => workspace.selectNode(slot.slotId, "F:/design/characters/homura", node)}>select</button>
      <button onClick={() => workspace.openEditor(slot.slotId)}>open</button>
      <span data-testid="slot-id">{slot.draftNode?.id ?? "empty"}</span>
      <span data-testid="legacy">{String((slot.draftNode?.legacy as Record<string, unknown> | undefined)?.source_file ?? "")}</span>
      <NodeWorkspaceEditor />
    </>
  );
}

function renderEditor() {
  render(<CustomWorkspaceProvider><Harness /></CustomWorkspaceProvider>);
  fireEvent.click(screen.getByText("select"));
  fireEvent.click(screen.getByText("open"));
}

function response(data: unknown): Response {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("NodeWorkspaceEditor", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps form edits temporary until Apply and preserves extension fields", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ node: { ...node, id: "edited", legacy: { source_file: "new.txt", keep: true } } }));
    renderEditor();

    fireEvent.change(screen.getByLabelText("Node ID"), { target: { value: "edited" } });
    fireEvent.change(screen.getByLabelText("extensions.legacy.source_file"), { target: { value: "new.txt" } });
    expect(screen.getByTestId("slot-id").textContent).toBe("homura");

    fireEvent.click(screen.getByRole("button", { name: "应用到本次运行" }));
    await waitFor(() => expect(screen.getByTestId("slot-id").textContent).toBe("edited"));
    expect(screen.getByTestId("legacy").textContent).toBe("new.txt");
  });

  it("syncs valid JSON into the form and keeps invalid JSON visible", () => {
    renderEditor();
    fireEvent.click(screen.getByRole("tab", { name: /JSON/ }));
    const json = screen.getByLabelText("Node JSON");
    fireEvent.change(json, { target: { value: JSON.stringify({ ...node, id: "json-edit" }) } });
    fireEvent.click(screen.getByRole("tab", { name: /Form/ }));
    expect((screen.getByLabelText("Node ID") as HTMLInputElement).value).toBe("json-edit");

    fireEvent.click(screen.getByRole("tab", { name: /JSON/ }));
    fireEvent.change(screen.getByLabelText("Node JSON"), { target: { value: "{broken" } });
    expect((screen.getByLabelText("Node JSON") as HTMLTextAreaElement).value).toBe("{broken");
    expect(screen.getByRole("alert").textContent).toContain("JSON 格式无效");
  });

  it("does not replace the form draft with structurally invalid JSON", () => {
    renderEditor();
    fireEvent.click(screen.getByRole("tab", { name: /JSON/ }));
    fireEvent.change(screen.getByLabelText("Node JSON"), { target: { value: JSON.stringify({ id: "broken", kind: "character" }) } });
    expect(screen.getByRole("alert").textContent).toContain("prompt.positive");
    fireEvent.click(screen.getByRole("tab", { name: /Form/ }));
    expect((screen.getByLabelText("Node ID") as HTMLInputElement).value).toBe("homura");
  });

  it("writes to the node library only after explicit Save", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ node }))
      .mockResolvedValueOnce(response({ schema: "tags-machine-core.web.node/v1", ref: "F:/design/characters/homura", node, form: {} }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderEditor();

    fireEvent.change(screen.getByLabelText("Node name"), { target: { value: "Saved Homura" } });
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /保存节点/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(String(fetchMock.mock.calls[1][0])).toContain("/nodes/save");
    expect(fetchMock.mock.calls[1][1]?.method).toBe("PUT");
  });

  it("confirms before closing with unapplied edits", () => {
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderEditor();
    fireEvent.change(screen.getByLabelText("Node ID"), { target: { value: "local" } });
    fireEvent.click(screen.getByRole("button", { name: "关闭节点编辑器" }));
    expect(confirmMock).toHaveBeenCalled();
    expect(screen.getByLabelText("Node ID")).toBeTruthy();
  });
});
