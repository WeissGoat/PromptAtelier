import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeEditorDocument } from "../api/types";
import type { NodeDocument } from "../nodes/types";
import { CustomWorkspaceProvider, useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { NodeWorkspaceEditor } from "./NodeWorkspaceEditor";

const node: NodeDocument = {
  schema: "tags-machine-core.node/v1",
  kind: "character",
  id: "homura",
  name: "Homura",
  prompt: { positive: [], negative: [] },
  tags: { character: ["akemi_homura"], hair: ["black_hair"] },
  legacy: { source_file: "old.txt" },
};

const editorDocument: NodeEditorDocument = {
  adapter: "character_meta_yaml/v1",
  role: "character",
  values: {
    id: "homura",
    name: "Homura",
    description: "source",
    positive: [],
    negative: [],
    identity_minimal: [],
    relations: {},
    tags: { character: ["akemi_homura"], hair: ["black_hair"] },
  },
  sources: [{ path: "F:/design/characters/homura/meta.yaml", format: "meta.yaml", sha256: "abc", writable: true }],
  capabilities: { save: true, multi_file: false },
};

function Harness() {
  const workspace = useCustomWorkspace();
  const slot = workspace.state.groups.character.primary;
  return (
    <>
      <button onClick={() => workspace.selectNode(slot.slotId, "F:/design/characters/homura", node, editorDocument)}>select</button>
      <button onClick={() => workspace.openEditor(slot.slotId)}>open</button>
      <span data-testid="slot-name">{slot.draftNode?.name ?? "empty"}</span>
      <NodeWorkspaceEditor />
    </>
  );
}

function renderEditor() {
  const view = render(<CustomWorkspaceProvider><Harness /></CustomWorkspaceProvider>);
  fireEvent.click(screen.getByText("select"));
  fireEvent.click(screen.getByText("open"));
  return view;
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

  it("does not preview or mark the node dirty when the source form is only opened", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ node }));
    renderEditor();

    await new Promise((resolve) => window.setTimeout(resolve, 300));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("slot-name").textContent).toBe("Homura");
  });

  it("shows only the character source form and updates the runtime draft through editor-preview", async () => {
    const updated = { ...node, name: "Edited Homura" };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ node: updated }));
    renderEditor();

    expect(screen.getByLabelText("Character name")).toBeTruthy();
    expect(screen.queryByText("legacy")).toBeNull();
    expect(screen.queryByText("renderers")).toBeNull();
    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "Edited Homura" } });

    await waitFor(() => expect(screen.getByTestId("slot-name").textContent).toBe("Edited Homura"));
    expect(String(vi.mocked(globalThis.fetch).mock.calls[0][0])).toContain("/nodes/editor-preview");
  });

  it("restores the source form draft after closing and remounting the workspace", async () => {
    const updated = { ...node, name: "Edited Homura" };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ node: updated }));
    const first = renderEditor();

    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "Edited Homura" } });
    await waitFor(() => expect(screen.getByTestId("slot-name").textContent).toBe("Edited Homura"));
    await waitFor(() => expect(localStorage.getItem("promptatelier.custom-workspace/v1")).toContain("Edited Homura"));
    fireEvent.click(screen.getByRole("button", { name: "关闭节点编辑器" }));
    await waitFor(() => {
      const stored = localStorage.getItem("promptatelier.custom-workspace/v1");
      expect(stored).toContain('"slotId":null');
      expect(stored).toContain("Edited Homura");
    });
    first.unmount();

    render(<CustomWorkspaceProvider><Harness /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("open"));

    expect((screen.getByLabelText("Character name") as HTMLInputElement).value).toBe("Edited Homura");
    expect(screen.getByTestId("slot-name").textContent).toBe("Edited Homura");
  });

  it("previews source diff before committing the save", async () => {
    const savedEditor = { ...editorDocument, values: { ...editorDocument.values, name: "Saved Homura" } };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/nodes/editor-preview")) return response({ node: { ...node, name: "Saved Homura" } });
      if (url.includes("/nodes/save-preview")) return response({
        schema: "tags-machine-core.web.node-save-preview/v1",
        preview_id: "save-1",
        node,
        files: [{ path: "F:/design/characters/homura/meta.yaml", relative: "meta.yaml", format: "meta.yaml", before_sha256: "abc", changed: true, diff: "--- meta.yaml\n+++ meta.yaml\n-name: Homura\n+name: Saved Homura\n", after_text: "name: Saved Homura\n" }],
        warnings: [],
        expires_at: Date.now() / 1000 + 600,
      });
      if (url.includes("/nodes/save-commit")) return response({ schema: "tags-machine-core.web.node/v2", ref: "F:/design/characters/homura", node: { ...node, name: "Saved Homura" }, form: {}, editor: savedEditor });
      throw new Error(`Unexpected request: ${url}`);
    });
    renderEditor();
    fireEvent.change(screen.getByLabelText("Character name"), { target: { value: "Saved Homura" } });
    await waitFor(() => expect(screen.getByText("临时节点已更新")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /保存节点/ }));
    expect(await screen.findByRole("dialog", { name: "保存节点源文件 Diff" })).toBeTruthy();
    expect(screen.getByText("+name: Saved Homura")).toBeTruthy();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/nodes/save-commit"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "确认写入 1 个文件" }));
    await waitFor(() => expect(screen.getByText("已保存到原数据源")).toBeTruthy());
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/nodes/save-commit"))).toBe(true);
  });

  it("keeps invalid runtime JSON visible without changing the source form", () => {
    renderEditor();
    fireEvent.click(screen.getByRole("tab", { name: /JSON/ }));
    fireEvent.change(screen.getByLabelText("Node JSON"), { target: { value: "{broken" } });
    expect(screen.getByRole("alert").textContent).toContain("JSON 格式无效");
    expect((screen.getByLabelText("Node JSON") as HTMLTextAreaElement).value).toBe("{broken");
  });
});
