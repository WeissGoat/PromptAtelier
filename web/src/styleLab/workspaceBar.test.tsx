import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WorkspaceInfo } from "./api";
import { suggestGroupName, WorkspaceBar } from "./WorkspaceBar";

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

const noop = () => undefined;

function Bar({
  onRename,
  renameRequest,
  onDelete = noop,
}: {
  onRename: (name: string) => Promise<boolean>;
  renameRequest?: number;
  onDelete?: () => void;
}) {
  return (
    <WorkspaceBar
      busy={false}
      current={group}
      imageCount={3}
      llm={null}
      onChangeProvider={noop}
      onCreateGroup={noop}
      onDelete={onDelete}
      onOpenFolder={noop}
      onRename={onRename}
      onRescan={noop}
      onRestoreImages={noop}
      onSelectWorkspace={noop}
      onToggleTranslate={noop}
      pretranslate={null}
      renameRequest={renameRequest}
      translateOn={false}
      translateProvider="google"
      translating={false}
      workspaces={[group]}
    />
  );
}

function renderBar(onRename: (name: string) => Promise<boolean>) {
  render(<Bar onRename={onRename} />);
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

  it("suggests a recognisable name for a new image group", () => {
    const now = new Date(2026, 9, 14);
    expect(suggestGroupName([{ name: "149600469_p0.png" }, { name: "149600469_p1.png" }], now)).toBe("149600469 2 张 · 10-14");
    expect(suggestGroupName([{ name: "ボテ腹奏ちゃん.png" }, { name: "IMG_3.webp" }, { name: "x.jpg" }], now)).toBe(
      "ボテ腹奏ちゃん 等 3 张 · 10-14",
    );
    expect(suggestGroupName([{ name: "kanade.png" }], now)).toBe("kanade · 10-14");
  });

  it("opens the name box when asked (right after a new group is created)", () => {
    const onRename = vi.fn().mockResolvedValue(true);
    const { rerender } = render(<Bar onRename={onRename} renameRequest={0} />);
    expect(screen.queryByRole("textbox", { name: "工作区名称" })).toBeNull();
    rerender(<Bar onRename={onRename} renameRequest={1} />);
    expect((screen.getByRole("textbox", { name: "工作区名称" }) as HTMLInputElement).value).toBe(group.name);
  });

  it("deletes the current workspace only after confirming", () => {
    const onDelete = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<Bar onDelete={onDelete} onRename={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "删除工作区" }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(confirm.mock.calls[0][0]).toContain("trash");
    fireEvent.click(screen.getByRole("button", { name: "删除工作区" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
    confirm.mockRestore();
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
