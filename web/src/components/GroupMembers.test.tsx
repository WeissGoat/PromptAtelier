import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createDefaultNodePoolSpec } from "../randomNodes/spec";
import { CustomWorkspaceProvider, useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { GroupMembers } from "./GroupMembers";

function response(data: unknown): Response {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

const members = ["a", "b", "c"].map((name) => ({ role: "action", ref: `/design/动作改2/group/${name}`, name, relative: `group/${name}` }));

function Harness() {
  const workspace = useCustomWorkspace();
  const slot = workspace.state.groups.action.primary;
  return (
    <div>
      <button onClick={() => {
        workspace.createRandom(slot.slotId);
        const spec = createDefaultNodePoolSpec("action");
        spec.source.value = "group";
        spec.drawMode = "sequential";
        workspace.updateRandomSpec(slot.slotId, spec);
        workspace.closeEditor();
      }} type="button">make group</button>
      <span data-testid="selection">{JSON.stringify(slot.randomSpec?.selection ?? null)}</span>
      <span data-testid="editing">{workspace.state.editor.memberRef ?? "none"}</span>
      <span data-testid="editing-name">{workspace.editorTarget?.draftNode?.name ?? "none"}</span>
      {slot.sourceKind === "random" ? <GroupMembers slot={slot} /> : null}
    </div>
  );
}

describe("GroupMembers", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("lists the whole group and narrows the run to checked members", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/node-pools/list-all")) return response({ schema: "list", role: "action", total: 3, items: members, stats: {} });
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<CustomWorkspaceProvider><Harness /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("make group"));

    expect(await screen.findByText("整组 3 个")).toBeTruthy();
    // 浏览成员时不带勾选条件，才能看到没勾选的成员。
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.spec.selection).toBeUndefined();

    fireEvent.click(screen.getByLabelText("勾选 b"));
    expect(screen.getByTestId("selection").textContent).toBe(JSON.stringify({ refs: [members[0].ref, members[2].ref] }));
    expect(screen.getByText("已选 2 / 3")).toBeTruthy();
    // 顺序位置只在勾选的成员里数：c 是第 2 个。
    expect(screen.getByText("#2")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /全不选/ }));
    expect(screen.getByTestId("selection").textContent).toBe(JSON.stringify({ refs: [] }));
    expect(screen.getByText("一个成员都没勾选，出图前至少勾选一个。")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /恢复整组/ }));
    expect(screen.getByTestId("selection").textContent).toBe("null");
  });

  it("opens a member in the editor as a temporary member draft", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/node-pools/list-all")) return response({ schema: "list", role: "action", total: 3, items: members, stats: {} });
      if (url.includes("/nodes/read")) {
        return response({
          schema: "tags-machine-core.web.node/v2",
          ref: members[1].ref,
          node: { schema: "tags-machine-core.node/v1", kind: "action", id: "b", name: "B node", prompt: { positive: [], negative: [] } },
          form: {},
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<CustomWorkspaceProvider><Harness /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByText("make group"));
    fireEvent.click(await screen.findByRole("button", { name: "编辑成员 b" }));

    await waitFor(() => expect(screen.getByTestId("editing").textContent).toBe(members[1].ref));
    expect(screen.getByTestId("editing-name").textContent).toBe("B node");
  });
});
