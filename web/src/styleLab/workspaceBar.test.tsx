import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WorkspaceInfo } from "./api";
import { WorkspaceBar } from "./WorkspaceBar";

const group: WorkspaceInfo = {
  id: "w1",
  name: "图片组 2026-10-13 01:24",
  kind: "files",
  root: "runtime/stylelab/workspaces/w1",
  data_dir: "runtime/stylelab/workspaces/w1",
  scan_dirs: [],
  files: [],
  created_at: 0,
  last_opened_at: 0,
};

function renderBar(onRename: (name: string) => Promise<boolean>) {
  const noop = vi.fn();
  render(
    <WorkspaceBar
      busy={false}
      current={group}
      imageCount={3}
      llm={null}
      onChangeProvider={noop}
      onCreateGroup={noop}
      onOpenFolder={noop}
      onRename={onRename}
      onRescan={noop}
      onRestoreImages={noop}
      onSelectWorkspace={noop}
      onToggleTranslate={noop}
      pretranslate={null}
      translateOn={false}
      translateProvider="google"
      translating={false}
      workspaces={[group]}
    />,
  );
}

afterEach(cleanup);

describe("workspace bar", () => {
  it("renames the current image group inline", async () => {
    const onRename = vi.fn().mockResolvedValue(true);
    renderBar(onRename);
    fireEvent.click(screen.getByRole("button", { name: "改名" }));
    const input = screen.getByRole("textbox", { name: "工作区名称" }) as HTMLInputElement;
    expect(input.value).toBe(group.name);
    fireEvent.change(input, { target: { value: "奏 立绘" } });
    fireEvent.submit(input.closest("form")!);
    expect(onRename).toHaveBeenCalledWith("奏 立绘");
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "工作区名称" })).toBeNull());

    // Esc 取消，不改名。
    fireEvent.click(screen.getByRole("button", { name: "改名" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "工作区名称" }), { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "工作区名称" })).toBeNull();
    expect(onRename).toHaveBeenCalledTimes(1);
  });

  it("keeps the input open when renaming fails", async () => {
    const onRename = vi.fn().mockResolvedValue(false);
    renderBar(onRename);
    fireEvent.click(screen.getByRole("button", { name: "改名" }));
    const input = screen.getByRole("textbox", { name: "工作区名称" });
    fireEvent.change(input, { target: { value: "新名字" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(onRename).toHaveBeenCalled());
    expect(screen.getByRole("textbox", { name: "工作区名称" })).toBeTruthy();
  });
});
