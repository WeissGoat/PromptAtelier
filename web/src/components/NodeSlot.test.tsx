import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeDocument } from "../nodes/types";
import type { NodeVariantSlot } from "../workspace/types";
import { NodeSlot } from "./NodeSlot";

const sourceNode: NodeDocument = {
  schema: "tags-machine-core.node/v1",
  kind: "character",
  id: "source",
  name: "source-file",
  prompt: { positive: [], negative: [] },
};

const baseSlot: NodeVariantSlot = {
  slotId: "primary-character",
  role: "character",
  mode: "primary",
  sourceRef: "F:/nodes/source",
  sourceNode,
  draftNode: sourceNode,
};

function response(data: unknown): Response {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderSlot(slot = baseSlot) {
  const props = {
    label: "Character",
    slot,
    placeholder: "搜索 Character 节点",
    onSelect: vi.fn(),
    onCreateBlank: vi.fn(),
    onRestore: vi.fn(),
    onClear: vi.fn(),
    onEdit: vi.fn(),
  };
  render(<NodeSlot {...props} />);
  return props;
}

async function runSearchDebounce() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300);
  });
}

describe("NodeSlot", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows the node filename instead of its path", () => {
    renderSlot();
    expect((screen.getByRole("combobox", { name: "Character" }) as HTMLInputElement).value).toBe("source-file");
    expect(screen.queryByDisplayValue("F:/nodes/source")).toBeNull();
  });

  it("marks modified and temporary node names with an asterisk", () => {
    const modified = { ...baseSlot, draftNode: { ...sourceNode, description: "edited" } };
    const view = render(<NodeSlot {...renderSlotProps(modified)} />);
    expect((screen.getByRole("combobox", { name: "Character" }) as HTMLInputElement).value).toBe("source-file *");

    view.rerender(<NodeSlot {...renderSlotProps({ ...baseSlot, sourceRef: null, sourceNode: null, draftNode: { ...sourceNode, name: null } })} />);
    expect((screen.getByRole("combobox", { name: "Character" }) as HTMLInputElement).value).toBe("source *");
  });

  it("reads and commits the exact selected ref", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ schema: "list", role: "character", nodes: [{ role: "character", name: "same", ref: "F:/nodes/second" }] }))
      .mockResolvedValueOnce(response({ schema: "node", ref: "F:/nodes/second", node: { ...sourceNode, id: "second" }, form: {} }));
    const props = renderSlot();
    fireEvent.focus(screen.getByRole("combobox", { name: "Character" }));
    await runSearchDebounce();
    await act(async () => {
      fireEvent.mouseDown(screen.getByRole("option", { name: "same" }));
      await Promise.resolve();
    });
    expect(props.onSelect).toHaveBeenCalledWith(expect.objectContaining({
      ref: "F:/nodes/second",
      node: expect.objectContaining({ id: "second" }),
    }));
    expect(String(fetchMock.mock.calls[1][0])).toContain(encodeURIComponent("F:/nodes/second"));
    expect(String(fetchMock.mock.calls[1][0])).toContain("role=character");
  });

  it("reloads a cached source node before opening an editor when sourceEditor is missing", async () => {
    const editor = {
      adapter: "character_meta_yaml/v1",
      role: "character",
      values: { id: "source" },
      sources: [],
      capabilities: { save: true },
    };
    const readResponse = {
      schema: "tags-machine-core.web.node/v2",
      ref: "F:/nodes/source",
      node: sourceNode,
      form: {},
      editor,
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response(readResponse));
    const props = renderSlot();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "编辑Character节点" }));
      await Promise.resolve();
    });

    expect(props.onEdit).toHaveBeenCalledWith(readResponse);
  });

  it("confirms before replacing a modified draft", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ schema: "list", role: "character", nodes: [{ role: "character", name: "new", ref: "F:/nodes/new" }] }));
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(false);
    const props = renderSlot({ ...baseSlot, draftNode: { ...sourceNode, id: "modified" } });
    fireEvent.focus(screen.getByRole("combobox", { name: "Character" }));
    await runSearchDebounce();
    fireEvent.mouseDown(screen.getByRole("option", { name: "new" }));
    expect(confirmMock).toHaveBeenCalled();
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("renders a delete command for compare slots", () => {
    const onRemove = vi.fn();
    render(<NodeSlot {...renderSlotProps({ ...baseSlot, slotId: "compare-1", mode: "compare" })} onRemove={onRemove} />);
    fireEvent.click(screen.getByRole("button", { name: "删除Character Compare节点" }));
    expect(onRemove).toHaveBeenCalled();
  });
});

function renderSlotProps(slot: NodeVariantSlot) {
  return {
    label: "Character",
    slot,
    placeholder: "搜索 Character 节点",
    onSelect: vi.fn(),
    onCreateBlank: vi.fn(),
    onRestore: vi.fn(),
    onClear: vi.fn(),
    onEdit: vi.fn(),
  };
}
