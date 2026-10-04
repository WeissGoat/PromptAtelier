import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BackgroundRunsPanel } from "./BackgroundRunsPanel";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
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

describe("BackgroundRunsPanel", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows the running item's phase, failures, and stops a run", async () => {
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
    render(<BackgroundRunsPanel onOpenImage={() => undefined} pollIntervalMs={60_000} />);

    expect(await screen.findByText("Random · 3 张")).toBeTruthy();
    expect(screen.getByText(/第 2\/3 项：pose-b · 正在启动 ComfyUI · 已 1[0-9] 秒/)).toBeTruthy();
    expect(screen.getByText("#1 pose-a：backend exploded")).toBeTruthy();
    expect(screen.getByText("成功 0 / 3 · 失败 1")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /停止/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/jobs/bg-7/cancel"))).toBe(true));
    expect(await screen.findByText("正在停止")).toBeTruthy();
  });

  it("stays hidden when there are no runs or the list cannot be loaded", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    const { container } = render(<BackgroundRunsPanel onOpenImage={() => undefined} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });
});
