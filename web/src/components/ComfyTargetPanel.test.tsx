import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { notifyComfyTargetsChanged } from "../comfyui/targetStatus";
import { ComfyTargetPanel } from "./ComfyTargetPanel";

function targetsResponse(modalState: "stopped" | "running") {
  return new Response(
    JSON.stringify({
      schema: "tags-machine-core.web.comfyui-targets/v1",
      default_target: "local",
      targets: [
        {
          name: "local",
          label: "本机 aki",
          location: "local",
          base_url: "http://127.0.0.1:8188",
          status: { state: "offline" },
          active_jobs: 0,
          last_used_at: null,
        },
        {
          name: "modal",
          label: "Modal 云端",
          location: "cloud",
          base_url: "https://example.modal.run",
          status: modalState === "running" ? { state: "running", shutdown_in_seconds: 90 } : { state: "stopped" },
          active_jobs: 0,
          last_used_at: null,
        },
      ],
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ComfyTargetPanel", () => {
  it("lists run locations, shows the selected status and reports changes", async () => {
    const fetchMock = vi.fn(async () => targetsResponse("stopped"));
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();

    const { rerender } = render(<ComfyTargetPanel onChange={onChange} value={undefined} />);
    expect(await screen.findByText("本机 aki 未启动")).toBeTruthy();
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["本机 aki", "Modal 云端"]);

    fireEvent.change(screen.getByLabelText("ComfyUI 运行位置"), { target: { value: "modal" } });
    expect(onChange).toHaveBeenCalledWith("modal");

    rerender(<ComfyTargetPanel onChange={onChange} value="modal" />);
    expect(screen.getByRole("status").textContent).toBe("云端已关机 · 下次生成需先启动（约 1–2 分钟）");
  });

  it("refreshes right away when a ComfyUI job starts or ends", async () => {
    const fetchMock = vi.fn(async () => targetsResponse("stopped"));
    vi.stubGlobal("fetch", fetchMock);
    render(<ComfyTargetPanel onChange={vi.fn()} value="modal" />);
    await screen.findByText("云端已关机 · 下次生成需先启动（约 1–2 分钟）");

    fetchMock.mockImplementation(async () => targetsResponse("running"));
    await act(async () => {
      notifyComfyTargetsChanged({ backend: "novelai" });
      notifyComfyTargetsChanged({ backend: "comfyui" });
    });

    expect(await screen.findByText("云端运行中 · 约 1 分 30 秒后自动关机")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
