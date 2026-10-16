import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeDocument, NodeRole } from "../nodes/types";
import { createDefaultNodePoolSpec } from "../randomNodes/spec";
import { CustomWorkspaceProvider, useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { CustomStudio } from "./CustomStudio";

const CLOTHING_SLOT = "clothing-primary-primary-character";
const pools: Record<string, string[]> = { clothing: ["c1", "c2"], action: ["a1", "a2", "a3"] };

function node(role: NodeRole, id: string): NodeDocument {
  return { schema: "tags-machine-core.node/v1", kind: role, id, name: id, prompt: { positive: [{ text: id }], negative: [] } };
}

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function Harness() {
  const workspace = useCustomWorkspace();
  function sequentialGroup(slotId: string, role: NodeRole, cursor: number) {
    workspace.createRandom(slotId);
    const spec = createDefaultNodePoolSpec(role);
    spec.source.value = role;
    spec.drawMode = "sequential";
    workspace.updateRandomSpec(slotId, spec);
    workspace.setPoolCursor(slotId, cursor);
  }
  const cursors = [CLOTHING_SLOT, "primary-action"].map((slotId) => workspace.findSlot(slotId)?.poolCursor ?? 0).join(",");
  return (
    <>
      <button onClick={() => {
        workspace.selectNode("primary-character", "characters/homura", node("character", "homura"));
        sequentialGroup(CLOTHING_SLOT, "clothing", 0);
        sequentialGroup("primary-action", "action", 1);
        workspace.closeEditor();
      }} type="button">cross</button>
      <button onClick={() => {
        workspace.selectNode("primary-character", "characters/homura", node("character", "homura"));
        sequentialGroup(CLOTHING_SLOT, "clothing", 0);
        workspace.closeEditor();
      }} type="button">clothing only</button>
      <span data-testid="cursors">{cursors}</span>
      <CustomStudio />
    </>
  );
}

function mockBackend() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (url.includes("/node-pools/list-all") || url.includes("/node-pools/scan")) {
      const items = pools[body.role].map((name) => ({ role: body.role, ref: `/${body.role}/${name}`, name }));
      return response({ total: items.length, items, offset: 0, has_more: false, stats: { total: items.length, unselected: 0 }, facets: {}, warnings: [] });
    }
    if (url.includes("/node-pools/collections")) return response({ items: [] });
    if (url.includes("/nodes/read")) {
      const params = new URL(url, "http://x").searchParams;
      const ref = params.get("ref")!;
      return response({ ref, node: node(params.get("role") as NodeRole, ref.split("/").pop()!), form: {} });
    }
    if (url.includes("/generate/batch")) return response({ id: "bg-1", name: "generate-batch", status: "queued", events: [] });
    if (url.includes("/jobs")) return response({ jobs: [] });
    throw new Error(`Unexpected request: ${url}`);
  });
}

function batches(fetchMock: ReturnType<typeof mockBackend>) {
  return fetchMock.mock.calls
    .filter(([input]) => String(input).includes("/generate/batch"))
    .map(([, init]) => JSON.parse(String(init?.body)));
}

describe("CustomStudio sequential groups", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("crosses clothing and action groups and advances both cursors", async () => {
    const fetchMock = mockBackend();
    render(<CustomWorkspaceProvider><Harness /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("cross"));
    fireEvent.click(screen.getByRole("button", { name: /Run All/ }));

    await waitFor(() => expect(batches(fetchMock)).toHaveLength(1));
    const body = batches(fetchMock)[0];
    expect(body.label).toBe("Sequential All · 5 组");
    expect(body.items.map((item: { label: string }) => item.label)).toEqual([
      "#1 c1 · #2 a2",
      "#1 c1 · #3 a3",
      "#2 c2 · #1 a1",
      "#2 c2 · #2 a2",
      "#2 c2 · #3 a3",
    ]);
    const third = body.items[2].compose_request.compose.nodes;
    expect(third.find((item: { role: string }) => item.role === "character").clothing_ref).toBe("/clothing/c2");
    expect(third.find((item: { role: string }) => item.role === "action").ref).toBe("/action/a1");
    expect(body.items[2].generate.output_dir).toContain("group_004_");
    await waitFor(() => expect(screen.getByTestId("cursors").textContent).toBe("2,0"));

    fireEvent.click(screen.getByRole("button", { name: /Generate Next/ }));
    expect(await screen.findByText(/跑到末尾/)).toBeTruthy();
  });

  it("runs a clothing-only sequential group instead of doing nothing", async () => {
    const fetchMock = mockBackend();
    render(<CustomWorkspaceProvider><Harness /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("clothing only"));
    fireEvent.click(screen.getByRole("button", { name: "Generate Next" }));

    await waitFor(() => expect(batches(fetchMock)).toHaveLength(1));
    const body = batches(fetchMock)[0];
    expect(body.label).toBe("Sequential · 1 组");
    expect(body.items[0].label).toBe("#1 c1");
    await waitFor(() => expect(screen.getByTestId("cursors").textContent).toBe("1,0"));
  });
});
