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

  it("does not restore a modified draft when confirmation is cancelled", () => {
    const modifiedSlot: NodeSlotState = { ...slot, draftNode: { ...node, id: "draft" } };
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { onRestore } = renderDrawer({ slot: modifiedSlot });
    fireEvent.click(screen.getByRole("button", { name: "还原原始节点" }));

    expect(confirmMock).toHaveBeenCalled();
    expect(onRestore).not.toHaveBeenCalled();
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
  it("saves a blank-origin node to an explicit target ref", async () => {
    const temporarySlot: NodeSlotState = { ...slot, sourceRef: null, sourceNode: null };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      schema: "tags-machine-core.web.node/v1",
      ref: "F:/design/characters/new-node",
      node,
      form: {},
    }), { status: 200 }));
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { onSaved, onClose } = renderDrawer({ slot: temporarySlot });

    fireEvent.change(screen.getByLabelText("Target ref"), { target: { value: "characters/new-node" } });
    fireEvent.click(screen.getAllByRole("button")[3]);

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("character", "F:/design/characters/new-node", node));
    expect(confirmMock).toHaveBeenCalled();
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).ref).toBe("characters/new-node");
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps a failed blank-origin save draft open", async () => {
    const temporarySlot: NodeSlotState = { ...slot, sourceRef: null, sourceNode: null };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("outside design root", { status: 400 }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { onSaved, onClose } = renderDrawer({ slot: temporarySlot });
    const editor = screen.getByRole("textbox", { name: /JSON/ });
    const draftText = JSON.stringify({ ...node, id: "unsaved" });

    fireEvent.change(editor, { target: { value: draftText } });
    fireEvent.change(screen.getByLabelText("Target ref"), { target: { value: "../outside" } });
    fireEvent.click(screen.getAllByRole("button")[3]);

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("outside design root"));
    expect((editor as HTMLTextAreaElement).value).toBe(draftText);
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("confirms before closing text changed since the last baseline", () => {
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { onClose } = renderDrawer();
    fireEvent.change(screen.getByRole("textbox", { name: /JSON/ }), { target: { value: JSON.stringify({ ...node, id: "local" }) } });

    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(confirmMock).toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    confirmMock.mockReturnValue(true);
    fireEvent.mouseDown(screen.getByRole("presentation"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("updates the baseline after Apply succeeds", async () => {
    const applied = { ...node, id: "applied" };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ node: applied }), { status: 200 }));
    const confirmMock = vi.spyOn(window, "confirm");
    const { onClose } = renderDrawer();
    fireEvent.change(screen.getByRole("textbox", { name: /JSON/ }), { target: { value: JSON.stringify(applied) } });

    fireEvent.click(screen.getAllByRole("button")[2]);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getAllByRole("button")[0]);

    expect(confirmMock).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("saves an existing node to sourceRef and updates the baseline", async () => {
    const saved = { ...node, id: "saved" };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      schema: "tags-machine-core.web.node/v1",
      ref: slot.sourceRef,
      node: saved,
      form: {},
    }), { status: 200 }));
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { onClose, onSaved } = renderDrawer();
    fireEvent.change(screen.getByRole("textbox", { name: /JSON/ }), { target: { value: JSON.stringify(saved) } });

    fireEvent.click(screen.getAllByRole("button")[3]);
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("character", slot.sourceRef, saved));
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).ref).toBe(slot.sourceRef);
    fireEvent.click(screen.getAllByRole("button")[0]);

    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
