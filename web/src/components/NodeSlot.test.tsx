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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
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

  it("ignores a stale read response when a newer node is selected", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ schema: "list", role: "character", nodes: [
        { role: "character", name: "A", ref: "F:/nodes/a" },
        { role: "character", name: "B", ref: "F:/nodes/b" },
      ] }))
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { selectNode } = renderSlot();

    fireEvent.click(screen.getByRole("button", { name: "Load 角色 nodes" }));
    await screen.findByRole("option", { name: "A F:/nodes/a" });
    fireEvent.click(screen.getByRole("option", { name: "A F:/nodes/a" }));
    fireEvent.click(screen.getByRole("option", { name: "B F:/nodes/b" }));

    second.resolve(response({ schema: "node", ref: "F:/nodes/b", node: { ...sourceNode, id: "b" }, form: {} }));
    await waitFor(() => expect(selectNode).toHaveBeenCalledWith("character", "F:/nodes/b", expect.objectContaining({ id: "b" })));

    first.resolve(response({ schema: "node", ref: "F:/nodes/a", node: { ...sourceNode, id: "a" }, form: {} }));
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(selectNode).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[2][0])).toContain(encodeURIComponent("F:/nodes/b"));
  });

  it("does not restore a late read after clearing the slot", async () => {
    const read = deferred<Response>();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ schema: "list", role: "character", nodes: [{ role: "character", name: "A", ref: "F:/nodes/a" }] }))
      .mockReturnValueOnce(read.promise);
    const { clear, selectNode } = renderSlot();

    fireEvent.click(screen.getByRole("button", { name: "Load 角色 nodes" }));
    await screen.findByRole("option", { name: "A F:/nodes/a" });
    fireEvent.click(screen.getByRole("option", { name: "A F:/nodes/a" }));
    fireEvent.click(screen.getByRole("button", { name: "清除角色节点" }));
    read.resolve(response({ schema: "node", ref: "F:/nodes/a", node: { ...sourceNode, id: "a" }, form: {} }));

    await waitFor(() => expect(clear).toHaveBeenCalledWith("character"));
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(selectNode).not.toHaveBeenCalled();
  });

  it("does not overwrite a new blank draft with a late read", async () => {
    const read = deferred<Response>();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ schema: "list", role: "character", nodes: [{ role: "character", name: "A", ref: "F:/nodes/a" }] }))
      .mockReturnValueOnce(read.promise);
    const { createBlank, selectNode } = renderSlot();

    fireEvent.click(screen.getByRole("button", { name: "Load 角色 nodes" }));
    await screen.findByRole("option", { name: "A F:/nodes/a" });
    fireEvent.click(screen.getByRole("option", { name: "A F:/nodes/a" }));
    fireEvent.click(screen.getByRole("button", { name: "新建空白角色节点" }));
    read.resolve(response({ schema: "node", ref: "F:/nodes/a", node: { ...sourceNode, id: "a" }, form: {} }));

    await waitFor(() => expect(createBlank).toHaveBeenCalledWith("character"));
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(selectNode).not.toHaveBeenCalled();
  });

  it("does not overwrite a restored source with a late read", async () => {
    const read = deferred<Response>();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ schema: "list", role: "character", nodes: [{ role: "character", name: "A", ref: "F:/nodes/a" }] }))
      .mockReturnValueOnce(read.promise);
    const { restore, selectNode } = renderSlot();

    fireEvent.click(screen.getByRole("button", { name: "Load 角色 nodes" }));
    await screen.findByRole("option", { name: "A F:/nodes/a" });
    fireEvent.click(screen.getByRole("option", { name: "A F:/nodes/a" }));
    fireEvent.click(screen.getByRole("button", { name: "还原角色节点" }));
    read.resolve(response({ schema: "node", ref: "F:/nodes/a", node: { ...sourceNode, id: "a" }, form: {} }));

    await waitFor(() => expect(restore).toHaveBeenCalledWith("character"));
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(selectNode).not.toHaveBeenCalled();
  });
  it("invalidates a pending read when Drawer Apply changes the slot", async () => {
    const read = deferred<Response>();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ schema: "list", role: "character", nodes: [{ role: "character", name: "A", ref: "F:/nodes/a" }] }))
      .mockReturnValueOnce(read.promise);
    const props = {
      label: "Character",
      role: "character" as const,
      slot: baseSlot,
      placeholder: "Search nodes",
      selectNode: vi.fn(),
      createBlank: vi.fn(),
      restore: vi.fn(),
      clear: vi.fn(),
      onEdit: vi.fn(),
    };
    const { rerender } = render(<NodeSlot {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Load Character nodes" }));
    await screen.findByRole("option", { name: "A F:/nodes/a" });
    fireEvent.click(screen.getByRole("option", { name: "A F:/nodes/a" }));
    rerender(<NodeSlot {...props} slot={{ ...baseSlot, draftNode: { ...sourceNode, id: "applied" } }} />);
    read.resolve(response({ schema: "node", ref: "F:/nodes/a", node: { ...sourceNode, id: "a" }, form: {} }));

    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(props.selectNode).not.toHaveBeenCalled();
  });

  it("invalidates a pending read when Drawer Save replaces the slot", async () => {
    const read = deferred<Response>();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ schema: "list", role: "character", nodes: [{ role: "character", name: "A", ref: "F:/nodes/a" }] }))
      .mockReturnValueOnce(read.promise);
    const props = {
      label: "Character",
      role: "character" as const,
      slot: baseSlot,
      placeholder: "Search nodes",
      selectNode: vi.fn(),
      createBlank: vi.fn(),
      restore: vi.fn(),
      clear: vi.fn(),
      onEdit: vi.fn(),
    };
    const { rerender } = render(<NodeSlot {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Load Character nodes" }));
    await screen.findByRole("option", { name: "A F:/nodes/a" });
    fireEvent.click(screen.getByRole("option", { name: "A F:/nodes/a" }));
    const saved = { ...sourceNode, id: "saved" };
    rerender(<NodeSlot {...props} slot={{ role: "character", sourceRef: "F:/nodes/saved", sourceNode: saved, draftNode: saved }} />);
    read.resolve(response({ schema: "node", ref: "F:/nodes/a", node: { ...sourceNode, id: "a" }, form: {} }));

    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(props.selectNode).not.toHaveBeenCalled();
  });
});
