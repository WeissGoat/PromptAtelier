import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeReadResponse } from "../api/types";
import type { NodeDocument, NodeRole } from "../nodes/types";
import { CustomWorkspaceProvider, useCustomWorkspace } from "./CustomWorkspaceProvider";
import { useOpenImageNodeInCustom, type ImageNodeOpenTarget } from "./useOpenImageNodeInCustom";

function node(role: NodeRole, id: string): NodeDocument {
  return {
    schema: "tags-machine-core.node/v1",
    kind: role,
    id,
    name: id,
    prompt: { positive: [{ text: id }], negative: [] },
  };
}

function readResponse(ref: string, role: NodeRole, id: string): NodeReadResponse {
  return {
    schema: "tags-machine-core.web.node/v2",
    ref,
    node: node(role, id),
    form: {},
    editor: {
      adapter: "test/v1",
      role,
      values: { id },
      sources: [],
      capabilities: {},
    },
  };
}

function Harness({
  onOpen,
  target,
}: {
  onOpen: () => void;
  target: ImageNodeOpenTarget;
}) {
  const workspace = useCustomWorkspace();
  const openNode = useOpenImageNodeInCustom(onOpen);
  return (
    <>
      <button
        onClick={() => workspace.selectNode(
          "primary-character",
          "F:/design/characters/homura",
          node("character", "homura"),
        )}
        type="button"
      >
        select character
      </button>
      <button onClick={() => workspace.createRandom("primary-action")} type="button">
        configure action group
      </button>
      <button onClick={() => void openNode(target)} type="button">
        open node
      </button>
      <span data-testid="editor-slot">{workspace.state.editor.slotId ?? "empty"}</span>
      <span data-testid="editor-member">{workspace.state.editor.memberRef ?? "empty"}</span>
      <span data-testid="action-compares">{workspace.state.groups.action.compares.length}</span>
      <span data-testid="action-compare-slot">{workspace.state.groups.action.compares[0]?.slotId ?? "empty"}</span>
    </>
  );
}

function renderHarness(target: ImageNodeOpenTarget) {
  const onOpen = vi.fn();
  render(
    <CustomWorkspaceProvider>
      <Harness onOpen={onOpen} target={target} />
    </CustomWorkspaceProvider>,
  );
  return onOpen;
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("useOpenImageNodeInCustom", () => {
  it("opens an existing fixed node without replacing its draft", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const onOpen = renderHarness({
      role: "character",
      name: "homura",
      ref: "F:/design/characters/homura",
    });

    fireEvent.click(screen.getByRole("button", { name: "select character" }));
    fireEvent.click(screen.getByRole("button", { name: "open node" }));

    await waitFor(() => expect(onOpen).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("editor-slot").textContent).toBe("primary-character");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("opens a selected member inside its existing random node group", async () => {
    const ref = "F:/design/actions/standing";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(readResponse(ref, "action", "standing")), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const onOpen = renderHarness({
      role: "action",
      name: "standing",
      ref,
      slotId: "primary-action",
      random: true,
    });

    fireEvent.click(screen.getByRole("button", { name: "configure action group" }));
    fireEvent.click(screen.getByRole("button", { name: "open node" }));

    await waitFor(() => expect(onOpen).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("editor-slot").textContent).toBe("primary-action");
    expect(screen.getByTestId("editor-member").textContent).toBe(ref);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/nodes/read?");
    expect(url).toContain(`ref=${encodeURIComponent(ref)}`);
    expect(url).toContain("role=action");
  });

  it("adds a compare slot when the generated node is not in the current workspace", async () => {
    const ref = "F:/design/actions/sitting";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(readResponse(ref, "action", "sitting")), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const onOpen = renderHarness({
      role: "action",
      name: "sitting",
      ref,
    });

    fireEvent.click(screen.getByRole("button", { name: "open node" }));

    await waitFor(() => expect(onOpen).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("action-compares").textContent).toBe("1");
    expect(screen.getByTestId("editor-slot").textContent).toBe(screen.getByTestId("action-compare-slot").textContent);
  });
});
