import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BatchStudio } from "./BatchStudio";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const targets = {
  schema: "tags-machine-core.web.comfyui-targets/v1",
  default_target: "local",
  targets: [
    {
      name: "local",
      label: "本机 aki",
      location: "local",
      base_url: "http://127.0.0.1:8188",
      status: { state: "online" },
      active_jobs: 0,
      last_used_at: null,
    },
    {
      name: "modal",
      label: "Modal 云端",
      location: "cloud",
      base_url: "https://example.modal.run",
      status: { state: "stopped" },
      active_jobs: 0,
      last_used_at: null,
    },
  ],
};

describe("BatchStudio", () => {
  beforeEach(() => localStorage.clear());

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders batch controls and preview action", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(targets)));

    render(<BatchStudio />);

    expect(screen.getByText("Batch Studio")).toBeTruthy();
    expect(screen.getByLabelText("Characters")).toBeTruthy();
    expect(screen.getByLabelText("Action Groups")).toBeTruthy();
    expect(screen.getByLabelText("Artist")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Plan Preview" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run Batch" })).toBeTruthy();
    expect(await screen.findByText("本机 aki 在线")).toBeTruthy();
  });

  it("runs the batch at the chosen ComfyUI location and remembers it", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/comfyui/targets")) return json(targets);
      if (url.endsWith("/batches/run")) return json({ id: "job-1", name: "batch", status: "queued" });
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = render(<BatchStudio />);
    await screen.findByText("本机 aki 在线");
    fireEvent.change(screen.getByLabelText("ComfyUI 运行位置"), { target: { value: "modal" } });
    fireEvent.click(screen.getByRole("button", { name: "Run Batch" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/batches/run"))).toBe(true));
    const runCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/batches/run"));
    expect(JSON.parse(String(runCall?.[1]?.body)).comfyui_target).toBe("modal");

    unmount();
    render(<BatchStudio />);
    expect(await screen.findByText("云端已关机 · 下次生成需先启动（约 1–2 分钟）")).toBeTruthy();
    expect((screen.getByLabelText("ComfyUI 运行位置") as HTMLSelectElement).value).toBe("modal");
  });
});
