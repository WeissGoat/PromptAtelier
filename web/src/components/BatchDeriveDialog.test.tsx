import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CompareRound } from "../compare/types";
import { BatchDeriveDialog } from "./BatchDeriveDialog";

const sampleRound: CompareRound = {
  id: "round-1",
  name: "第 1 批对比",
  template: {
    prompt: "1girl, solo",
    negative: "lowres",
    seed: 12345,
    width: 512,
    height: 512,
    steps: 28,
    scale: 5.0,
  },
  basePrompt: "1girl, solo",
  variants: [
    {
      id: "var-1",
      name: "对照组",
      prompt: "1girl, solo",
      diff: { added: [], removed: [], unchanged: ["1girl", "solo"], tokens: [] },
      seedOverride: null,
      status: "idle",
      jobId: null,
    },
    {
      id: "var-2",
      name: "变体 1-B",
      prompt: "1girl, solo, smile",
      diff: { added: ["smile"], removed: [], unchanged: ["1girl", "solo"], tokens: [] },
      seedOverride: null,
      status: "idle",
      jobId: null,
    },
  ],
  status: "idle",
};

describe("BatchDeriveDialog", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("does not render when isOpen is false", () => {
    render(
      <BatchDeriveDialog
        isOpen={false}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        sourceRound={sampleRound}
      />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders when isOpen is true and parses uploaded images", async () => {
    const mockInspectResponse = {
      filename: "test_char.png",
      source_path: "f:/outputs/test_char.png",
      dimensions: { width: 832, height: 1216 },
      prompt: "masterpiece, 1girl, standing",
      negative_prompt: "worst quality",
      seed: 888999,
      steps: 28,
      scale: 5.0,
      sampler: "k_euler",
      model: "nai-diffusion-4-5-full",
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/image-meta/inspect")) {
        return new Response(JSON.stringify(mockInspectResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("Not found", { status: 404 });
    });

    const onConfirm = vi.fn();
    const onClose = vi.fn();

    render(
      <BatchDeriveDialog
        isOpen={true}
        onClose={onClose}
        onConfirm={onConfirm}
        sourceRound={sampleRound}
      />,
    );

    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText(/多图批量派生新批次/)).toBeTruthy();
    expect(screen.getByText("第 1 批对比")).toBeTruthy();

    // Create a mock file and simulate input change
    const file = new File(["fake image content"], "test_char.png", { type: "image/png" });
    const input = screen.getByRole("dialog").querySelector('input[type="file"]') as HTMLInputElement;

    fireEvent.change(input, { target: { files: [file] } });

    // Wait for the card to be fully ready
    await waitFor(() => {
      expect(screen.getByText(/832×1216/)).toBeTruthy();
    });

    expect(screen.getByText(/Seed: 888999/)).toBeTruthy();

    // Click confirm button (default autoRun is true)
    const confirmBtn = screen.getByRole("button", { name: /确定派生 1 个新批次/ });
    fireEvent.click(confirmBtn);

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith(
      [
        expect.objectContaining({
          filename: "test_char.png",
          template: expect.objectContaining({
            prompt: "masterpiece, 1girl, standing",
            seed: 888999,
            width: 832,
            height: 1216,
          }),
        }),
      ],
      true, // autoRun
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("can toggle autoRun and remove an item from the list", async () => {
    const mockInspectResponse = {
      filename: "test_char_2.png",
      source_path: "f:/outputs/test_char_2.png",
      dimensions: { width: 512, height: 512 },
      prompt: "cat",
      negative_prompt: "",
      seed: 111,
      steps: 28,
      scale: 5.0,
      sampler: "k_euler",
      model: "nai-diffusion-4-5-full",
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(JSON.stringify(mockInspectResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const onConfirm = vi.fn();
    render(
      <BatchDeriveDialog
        isOpen={true}
        onClose={vi.fn()}
        onConfirm={onConfirm}
        sourceRound={sampleRound}
      />,
    );

    const file = new File(["content"], "test_char_2.png", { type: "image/png" });
    const input = screen.getByRole("dialog").querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("512×512")).toBeTruthy();
    });

    // Toggle autoRun checkbox off
    const autoRunCheckbox = screen.getByRole("checkbox") as HTMLInputElement;
    expect(autoRunCheckbox.checked).toBe(true);
    fireEvent.click(autoRunCheckbox);
    expect(autoRunCheckbox.checked).toBe(false);

    // Confirm button text updates to "确定派生 1 个新批次"
    const confirmBtn = screen.getByRole("button", { name: /确定派生 1 个新批次/ });
    expect(confirmBtn.textContent).not.toContain("并开始出图");

    // Remove the item
    const removeBtn = screen.getByRole("button", { name: /移除 test_char_2.png/ });
    fireEvent.click(removeBtn);

    // List should now be empty and confirm button disabled
    expect(screen.queryByText("test_char_2.png")).toBeNull();
    expect((confirmBtn as HTMLButtonElement).disabled).toBe(true);
  });
});
