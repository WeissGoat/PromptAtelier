import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeVariantSlot } from "../workspace/types";
import { NodeGroupSummary } from "./NodeGroupSummary";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function groupSlot(drawMode: "random" | "sequential", poolCursor = 0): NodeVariantSlot {
  return {
    slotId: "primary-action",
    role: "action",
    mode: "primary",
    sourceKind: "random",
    sourceRef: null,
    sourceNode: null,
    draftNode: null,
    poolCursor,
    randomSpec: {
      source: { type: "folder", value: "new", recursive: false, include_names: [], exclude_names: [] },
      filters: { classify: {} },
      drawMode,
    },
  } as unknown as NodeVariantSlot;
}

function scanResponse(offset: number) {
  return {
    total: 12,
    source_total: 12,
    offset,
    items: [
      { role: "action", ref: "F:/a/n3", name: "n3", position: offset, has_preview: true },
      { role: "action", ref: "F:/a/n4", name: "n4", position: offset + 1, has_preview: false },
    ],
  };
}

describe("NodeGroupSummary", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows the next member from the sequential cursor", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const body = JSON.parse(String(init?.body));
      return response(scanResponse(body.offset));
    });
    render(<NodeGroupSummary slot={groupSlot("sequential", 2)} />);

    expect(await screen.findByText("共 12 个 · 下一个 #3 n3")).toBeTruthy();
    expect(screen.getByText("节点组 · 顺序")).toBeTruthy();
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).offset).toBe(2);
    expect(screen.getByRole("img", { name: "n3 预览图" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "n4 没有预览图" })).toBeTruthy();
    expect(screen.getByText("+8")).toBeTruthy();
  });

  it("describes a random group and a finished sequential group", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const body = JSON.parse(String(init?.body));
      return response(body.offset >= 12 ? { ...scanResponse(body.offset), items: [] } : scanResponse(body.offset));
    });
    const { rerender } = render(<NodeGroupSummary slot={groupSlot("random")} />);
    expect(await screen.findByText("共 12 个 · 每次随机抽一个")).toBeTruthy();

    rerender(<NodeGroupSummary slot={groupSlot("sequential", 12)} />);
    await waitFor(() => expect(screen.getByText("共 12 个 · 已跑完，请重置位置")).toBeTruthy());
  });
});
