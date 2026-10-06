import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GenerationTasksPanel } from "./GenerationTasksPanel";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function runningJob(status = "running") {
  return {
    id: "bg-7",
    name: "generate-batch",
    status,
    created_at: 1_780_000_000,
    events: [
      { type: "comfyui_queued", item_index: 0, at: 1 },
      { type: "comfyui_starting", item_index: 1, at: Date.now() / 1000 - 12 },
    ],
    result: {
      label: "Random · 3 张",
      kind: "random",
      output_dir: "outputs/compares/random_x",
      total: 3,
      counts: { queued: 1, running: 1, succeeded: 0, failed: 1, cancelled: 0 },
      items: [
        { index: 0, label: "pose-a", status: "failed", images: [], error: "backend exploded" },
        { index: 1, label: "pose-b", seed: 9, status: "running", images: [], error: null },
        { index: 2, label: "pose-c", status: "queued", images: [], error: null },
      ],
    },
  };
}

function interruptedJob(status = "interrupted") {
  return {
    id: "bg-8",
    name: "generate-batch",
    status,
    created_at: 1_780_000_000,
    updated_at: 1_780_000_090,
    events: [],
    result: {
      label: "Sequential · 2 个动作",
      kind: "sequential",
      output_dir: "outputs/compares/sequential_x",
      total: 2,
      counts: { queued: 1, running: 0, succeeded: 1, failed: 0, cancelled: 0 },
      items: [
        { index: 0, label: "#1 standing", seed: 5, status: "succeeded", images: [{ path: "outputs/a.png", meta: { elapsed_seconds: 7.3 } }], error: null },
        { index: 1, label: "#2 sitting", seed: 6, status: "queued", images: [], error: null },
      ],
    },
  };
}

describe("GenerationTasksPanel", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows the running item's phase, failures as tiles, and stops a run", async () => {
    let cancelled = false;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/jobs/bg-7/cancel")) {
        cancelled = true;
        return response(runningJob("cancelling"));
      }
      if (url.includes("/jobs?name=generate-batch")) return response({ jobs: [runningJob(cancelled ? "cancelling" : "running")] });
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<GenerationTasksPanel onOpenImage={() => undefined} pollIntervalMs={60_000} />);

    expect(await screen.findByText("Random · 3 张")).toBeTruthy();
    expect(screen.getByText(/正在启动 ComfyUI · 已 1[0-9] 秒/)).toBeTruthy();
    expect(screen.getByText("backend exploded")).toBeTruthy();
    expect(screen.getByText("排队中", { selector: "small" })).toBeTruthy();
    expect(screen.getByText("成功 0 / 3 · 失败 1 · 正在跑第 2 项")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /停止/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/jobs/bg-7/cancel"))).toBe(true));
    expect(await screen.findByText("正在停止")).toBeTruthy();
  });

  it("offers to resume an interrupted job and opens its images", async () => {
    let resumed = false;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/generate/batch/bg-8/resume")) {
        resumed = true;
        return response(interruptedJob("queued"));
      }
      if (url.includes("/jobs?name=generate-batch")) return response({ jobs: [interruptedJob(resumed ? "queued" : "interrupted")] });
      throw new Error(`Unexpected request: ${url}`);
    });
    const onOpenImage = vi.fn();
    render(<GenerationTasksPanel onOpenImage={onOpenImage} pollIntervalMs={60_000} />);

    expect(await screen.findByText("已中断")).toBeTruthy();
    expect(screen.getByText(/Web 后端重启时这个任务还没跑完/)).toBeTruthy();
    const image = screen.getByRole("img", { name: "#1 standing" }) as HTMLImageElement;
    expect(image.src).toContain("/results/thumb?path=outputs%2Fa.png&size=320");
    expect(screen.getByText("7.3 秒")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "打开 #1 standing 大图" }));
    expect(onOpenImage).toHaveBeenCalledWith({ index: 0, items: [expect.objectContaining({ path: "outputs/a.png", label: "#1 standing" })] });

    fireEvent.click(screen.getByRole("button", { name: /继续剩余 1 项/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/generate/batch/bg-8/resume"))).toBe(true));
    expect(await screen.findByText("排队中", { selector: ".status-pill" })).toBeTruthy();
  });

  it("remembers the thumbnail size and shows an empty state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ jobs: [] }));
    render(<GenerationTasksPanel onOpenImage={() => undefined} />);

    expect(await screen.findByText(/还没有出图任务/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "大" }));
    expect(localStorage.getItem("promptatelier.task-tile-size/v1")).toBe("l");
    expect(screen.getByRole("button", { name: "大" }).getAttribute("aria-pressed")).toBe("true");
  });
});
