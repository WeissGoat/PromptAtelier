import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeDocument, NodeSlotState } from "../nodes/types";
import { NodeEditorDrawer } from "./NodeEditorDrawer";

const node: NodeDocument = {
  schema: "tags-machine-core.node/v1",
  kind: "character",
  id: "homura",
  prompt: { positive: [], negative: [] },
};

const slot: NodeSlotState = {
  role: "character",
  sourceRef: "F:/design/character/homura",
  sourceNode: node,
  draftNode: node,
};

function renderDrawer(overrides: Partial<React.ComponentProps<typeof NodeEditorDrawer>> = {}) {
  const props = {
    open: true,
    slot,
    onClose: vi.fn(),
    onApply: vi.fn(),
    onRestore: vi.fn(),
    onSaved: vi.fn(),
    ...overrides,
  };
  render(<NodeEditorDrawer {...props} />);
  return props;
}

describe("NodeEditorDrawer", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps edits local until apply is clicked", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ node }), { status: 200 }));
    const { onApply } = renderDrawer();
    fireEvent.change(screen.getByLabelText("节点 JSON"), { target: { value: JSON.stringify({ ...node, id: "draft" }) } });
    expect(onApply).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "应用到本次运行" }));
    await waitFor(() => expect(onApply).toHaveBeenCalledWith("character", node));
  });

  it("shows validation error for malformed JSON", async () => {
    const { onApply } = renderDrawer();
    const editor = screen.getByLabelText("节点 JSON");
    fireEvent.change(editor, { target: { value: "{ not json" } });
    fireEvent.click(screen.getByRole("button", { name: "应用到本次运行" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("JSON 格式无效"));
    expect((editor as HTMLTextAreaElement).value).toBe("{ not json");
    expect(onApply).not.toHaveBeenCalled();
  });

  it("restores the source node", () => {
    const { onRestore } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "还原原始节点" }));
    expect(onRestore).toHaveBeenCalledWith("character");
  });

  it("does not call save while applying a temporary edit", async () => {
    const temporarySlot: NodeSlotState = { ...slot, sourceRef: null, sourceNode: null };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ node }), { status: 200 }));
    renderDrawer({ slot: temporarySlot });
    fireEvent.click(screen.getByRole("button", { name: "应用到本次运行" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).toContain("/nodes/preview");
    expect((screen.getByRole("button", { name: "保存到节点库" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
