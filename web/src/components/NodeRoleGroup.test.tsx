import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CustomWorkspaceProvider } from "../workspace/CustomWorkspaceProvider";
import { NodeRoleGroup } from "./NodeRoleGroup";

describe("NodeRoleGroup", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("adds and removes multiple compare slots", () => {
    render(<CustomWorkspaceProvider><NodeRoleGroup role="artist" /></CustomWorkspaceProvider>);
    fireEvent.click(screen.getByRole("button", { name: "新增Artist Compare" }));
    fireEvent.click(screen.getByRole("button", { name: "新增Artist Compare" }));
    expect(screen.getAllByText("Compare")).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: "删除Artist Compare节点" })[0]);
    expect(screen.getAllByText("Compare")).toHaveLength(1);
  });
});
