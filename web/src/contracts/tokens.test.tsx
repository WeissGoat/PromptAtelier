import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TokenUsage } from "../api/types";
import { formatTokenUsage } from "../components/PromptPreview";
import { checkFinalLengths, confirmOverLimit, formatMismatch } from "./ContractGeneratePanel";
import type { ContractDetail } from "./types";
import { TokenBadge } from "./FrameCard";

const post = vi.fn();
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  apiPost: (...args: unknown[]) => post(...args),
}));

function usage(patch: Partial<TokenUsage> = {}): TokenUsage {
  return { tokenizer: "t5", limit: 512, exact: true, shared: true, base: 100, characters: [20], total: 120, over: false, ...patch };
}

describe("token usage display", () => {
  it("shows n / limit with tone by ratio", () => {
    const { rerender } = render(<TokenBadge usage={usage()} />);
    expect(screen.getByText("120 / 512").className).toContain("ct-pill-ok");
    rerender(<TokenBadge usage={usage({ total: 480 })} />);
    expect(screen.getByText("480 / 512").className).toContain("ct-pill-warn");
    rerender(<TokenBadge usage={usage({ total: 600, over: true, exact: false })} />);
    expect(screen.getByText("≈600 / 512").className).toContain("ct-pill-err");
  });

  it("renders nothing without a limit", () => {
    const { container } = render(<TokenBadge usage={usage({ limit: null })} />);
    expect(container.textContent).toBe("");
  });

  it("formats preview summary", () => {
    expect(formatTokenUsage(usage())).toBe("120 / 512 · T5（主 100 + 角色 20）");
    expect(formatTokenUsage(usage({ tokenizer: "clip", shared: false, characters: [], total: 300, limit: 225, over: true })))
      .toBe("300 / 225 · CLIP · 超限，超出部分会被截断");
  });

  it("checks final lengths through compose-preview", async () => {
    post.mockReset();
    post.mockResolvedValueOnce({ status: "ready", token_usage: usage({ total: 530, over: true }) });
    post.mockResolvedValueOnce({ status: "ready" });
    post.mockRejectedValueOnce(new Error("boom"));
    const request = { compose: {}, render: {} } as never;
    const result = await checkFinalLengths([
      { frameId: "f01", request },
      { frameId: "f02", request },
      { frameId: "f03", request },
    ]);
    expect(post).toHaveBeenCalledWith("/compose-preview", request);
    expect(result[0].usage?.over).toBe(true);
    expect(result[1].error).toBe("这个后端不限长度");
    expect(result[2].error).toContain("boom");
  });

  it("flags artist model that does not match the contract format", () => {
    const detail = { profile: { id: "nai-v4.5", label: "NovelAI V4.5", models: ["nai-diffusion-4-5-full"] } } as unknown as ContractDetail;
    expect(formatMismatch(detail, [{ frameId: "f01", usage: usage({ model: "nai-diffusion-4-5-full" }) }])).toBe("");
    expect(formatMismatch(detail, [{ frameId: "f01", usage: usage({ model: "nai-diffusion-3" }) }])).toContain("nai-diffusion-3");
    expect(formatMismatch(detail, [{ frameId: "f01", error: "x" }])).toBe("");
  });

  it("asks for confirmation only when a frame is over the limit", () => {
    const confirm = vi.fn(() => false);
    expect(confirmOverLimit([{ frameId: "f01", usage: usage() }, { frameId: "f02", error: "x" }], confirm)).toBe(true);
    expect(confirm).not.toHaveBeenCalled();
    const over = [
      { frameId: "f01", usage: usage() },
      { frameId: "f02", usage: usage({ total: 530, over: true, model: "nai-diffusion-4-5-full" }) },
    ];
    expect(confirmOverLimit(over, confirm)).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(1);
    const message = (confirm.mock.calls[0] as unknown as [string])[0];
    expect(message).toContain("f02：530 / 512");
    expect(message).not.toContain("f01");
    expect(message).toContain("nai-diffusion-4-5-full");
    expect(confirmOverLimit(over, () => true)).toBe(true);
  });
});
