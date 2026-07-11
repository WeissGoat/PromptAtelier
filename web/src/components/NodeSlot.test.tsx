import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeDocument, NodeSlotState } from "../nodes/types";
import { NodeSlot } from "./NodeSlot";

const sourceNode: NodeDocument = {
  schema: "tags-machine-core.node/v1",
  kind: "character",
  id: "source",
  prompt: { positive: [], negative: [] },
};

const baseSlot: NodeSlotState = {
  role: "character",
  sourceRef: "F:/nodes/source",
  sourceNode,
  draftNode: sourceNode,
};

function renderSlot(slot = baseSlot) {
  const props = {
    label: "角色",
    role: "character" as const,
    slot,
    placeholder: "搜索节点",
    selectNode: vi.fn(),
    createBlank: vi.fn(),
    restore: vi.fn(),
    clear: vi.fn(),
    onEdit: vi.fn(),
  };
  render(<NodeSlot {...props} />);
  return props;
}

function response(data: unknown): Response {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("NodeSlot", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("does not restore a modified draft when confirmation is cancelled", () => {
    const modifiedSlot: NodeSlotState = { ...baseSlot, draftNode: { ...sourceNode, id: "draft" } };
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { restore } = renderSlot(modifiedSlot);

    fireEvent.click(screen.getByRole("button", { name: "还原角色节点" }));

    expect(confirmMock).toHaveBeenCalled();
    expect(restore).not.toHaveBeenCalled();
  });

  it("uses the exact ref for an explicitly selected duplicate name", async () => {
    const selected = { role: "character", name: "同名", ref: "F:/nodes/second", relative: "set-b/同名" };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ schema: "list", role: "character", nodes: [
        { role: "character", name: "同名", ref: "F:/nodes/first", relative: "set-a/同名" },
        selected,
      ] }))
      .mockResolvedValueOnce(response({ schema: "tags-machine-core.web.node/v1", ref: selected.ref, node: { ...sourceNode, id: "second" }, form: {} }));
    const { selectNode } = renderSlot();

    fireEvent.click(screen.getByRole("button", { name: "Load 角色 nodes" }));
    await screen.findByRole("option", { name: "同名 set-b/同名" });
    fireEvent.click(screen.getByRole("option", { name: "同名 set-b/同名" }));

    await waitFor(() => expect(selectNode).toHaveBeenCalledWith("character", selected.ref, expect.objectContaining({ id: "second" })));
    expect(String(fetchMock.mock.calls[1][0])).toContain(encodeURIComponent(selected.ref));
  });

  it("keeps the current node displayed when replacing is cancelled or reading fails", async () => {
    const modifiedSlot: NodeSlotState = { ...baseSlot, draftNode: { ...sourceNode, id: "draft" } };
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { rerender } = render(<NodeSlot
      label="角色"
      role="character"
      slot={modifiedSlot}
      placeholder="搜索节点"
      selectNode={vi.fn()}
      createBlank={vi.fn()}
      restore={vi.fn()}
      clear={vi.fn()}
      onEdit={vi.fn()}
    />);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ schema: "list", role: "character", nodes: [
      { role: "character", name: "新节点", ref: "F:/nodes/new" },
    ] }));

    fireEvent.click(screen.getByRole("button", { name: "Load 角色 nodes" }));
    await screen.findByRole("option", { name: "新节点 F:/nodes/new" });
    fireEvent.click(screen.getByRole("option", { name: "新节点 F:/nodes/new" }));
    expect(confirmMock).toHaveBeenCalled();
    expect((screen.getByLabelText("角色") as HTMLInputElement).value).toBe(baseSlot.sourceRef);

    confirmMock.mockReturnValue(true);
    rerender(<NodeSlot
      label="角色"
      role="character"
      slot={modifiedSlot}
      placeholder="搜索节点"
      selectNode={vi.fn()}
      createBlank={vi.fn()}
      restore={vi.fn()}
      clear={vi.fn()}
      onEdit={vi.fn()}
    />);
    fetchMock.mockRejectedValueOnce(new Error("read failed"));
    fireEvent.click(screen.getByRole("option", { name: "新节点 F:/nodes/new" }));

    await waitFor(() => expect(screen.getByText("read failed")).toBeTruthy());
    expect((screen.getByLabelText("角色") as HTMLInputElement).value).toBe(baseSlot.sourceRef);
  });
});
