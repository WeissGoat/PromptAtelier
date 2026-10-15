import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageRecord, ParamDiff, StyleLabRun } from "./api";

const api = vi.hoisted(() => ({ revealFile: vi.fn(), getFileInfo: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<typeof import("./api")>()), ...api }));

import { ImageViewerProvider } from "./ImageViewer";
import { RunPanel } from "./RunPanel";

const source: ImageRecord = {
  id: "src",
  path: "F:/corpus/a,b.png",
  rel_path: "a,b.png",
  size_bytes: 1,
  mtime_ns: 1,
  post: null,
  width: 832,
  height: 1216,
  has_metadata: true,
  source_label: null,
  model: "nai-diffusion-5-full",
  request_type: "PromptGenerateRequest",
  prompt: "1girl",
  negative_prompt: "",
  char_captions: [],
  seed: 42,
  steps: 28,
  scale: 5,
  cfg_rescale: 0,
  sampler: "k_euler_ancestral",
  noise_schedule: "karras",
  vibe: { count: 0, hashes: [], strengths: [], information_extracted: [] },
  flags: [],
};

const extraNote = "原图的出图客户端在元数据里另存的字段";

function diff(key: string, left: unknown, right: unknown, note?: string): ParamDiff {
  return { path: `$.parameters.${key}`, key, kind: "key", left, right, expected: Boolean(note), note };
}

function run(): StyleLabRun {
  return {
    id: "run1",
    kind: "regenerate",
    status: "succeeded",
    created_at: 0,
    finished_at: 1,
    job_id: null,
    source: { image_id: "src", path: source.path, rel_path: source.rel_path },
    settings: { count: 1, seed_mode: "source", seed: null, size_mode: "source", width: null, height: null, overrides: {} },
    expected_diff_keys: [],
    warnings: [],
    items: [
      {
        index: 0,
        seed: 42,
        status: "succeeded",
        image_path: "runs/run1/out.png",
        compare: {
          verdict: "match",
          similarity: 1,
          dhash_distance: 0,
          param_diff_count: 0,
          param_diff_no_resolution_count: 0,
          diffs: [
            diff("Software", "NovelAI", "<missing>", extraNote),
            diff("cfg_scale", 4.32, "<missing>", extraNote),
            diff("my_flag", true, "<missing>", "网页端独有"),
          ],
        },
      },
    ],
  };
}

describe("RunPanel", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    api.getFileInfo.mockResolvedValue({ path: source.path, size_bytes: 1, modified_at: 0 });
  });

  it("folds ignorable diffs that share a reason into one row", () => {
    render(
      <ImageViewerProvider workspaceId="ws">
        <RunPanel image={source} onCancel={() => undefined} runs={[run()]} workspaceId="ws" />
      </ImageViewerProvider>,
    );
    expect(screen.queryByText("Software")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText("2 项")).toBeTruthy();
    expect(screen.getByText("Software").getAttribute("title")).toContain("重生：（没有这个字段）");
    // 只有一项的原因照常单独一行。
    expect(screen.getByText("my_flag")).toBeTruthy();
    expect(screen.getByText("（没有这个字段）")).toBeTruthy();
  });

  it("opens the compared images in the viewer and reveals the file", async () => {
    api.revealFile.mockResolvedValue({ path: source.path });
    api.getFileInfo.mockImplementation((_ws: string, file: { imageId?: string; path?: string }) =>
      Promise.resolve({ path: file.imageId ? source.path : "F:/runtime/runs/run1/out.png", size_bytes: 2048, modified_at: 0 }),
    );
    render(
      <ImageViewerProvider workspaceId="ws">
        <RunPanel image={source} onCancel={() => undefined} runs={[run()]} workspaceId="ws" />
      </ImageViewerProvider>,
    );
    fireEvent.click(screen.getByRole("img", { name: "重生" }).closest("button")!);
    const dialog = screen.getByRole("dialog", { name: "图片详情" });
    expect(dialog.textContent).toContain("2 / 2");
    await waitFor(() => expect(dialog.textContent).toContain("F:/runtime/runs/run1/out.png"));
    expect(dialog.textContent).toContain("2.0 KB");

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(dialog.textContent).toContain("F:/corpus/a,b.png");
    fireEvent.click(screen.getByRole("button", { name: /打开所在位置/ }));
    await waitFor(() => expect(screen.getByText("已在资源管理器中打开")).toBeTruthy());
    expect(api.revealFile).toHaveBeenCalledWith("ws", { imageId: "src" });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
