import { cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";

import * as apiClient from "../api/client";
import type { NovelAIUsageInfo } from "../api/types";
import { NovelAIUsageBadge } from "./NovelAIUsageBadge";

describe("NovelAIUsageBadge", () => {
  const sampleUsage: NovelAIUsageInfo = {
    configured: true,
    token_masked: "pst-...abcd",
    active: true,
    tier: 3,
    tier_name: "Opus",
    anlas: 4500,
    fixed_anlas: 0,
    purchased_anlas: 4500,
    usage_percent: 65.5,
    time_until_next_percent: 1800,
    unlimited_v5_eligible: true,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders usage badge when loaded", async () => {
    vi.spyOn(apiClient, "getNovelAIUsage").mockResolvedValue(sampleUsage);

    render(<NovelAIUsageBadge />);

    expect(screen.getByText(/查询中/)).toBeDefined();

    await waitFor(() => {
      expect(screen.getByText(/V5 65.5%/)).toBeDefined();
      expect(screen.getByText(/4\.5k/)).toBeDefined();
    });
  });

  it("opens popover with details on click and refreshes", async () => {
    vi.spyOn(apiClient, "getNovelAIUsage").mockResolvedValue(sampleUsage);
    const refreshSpy = vi.spyOn(apiClient, "refreshNovelAIUsage").mockResolvedValue({
      ...sampleUsage,
      usage_percent: 70.0,
    });

    render(<NovelAIUsageBadge />);

    await waitFor(() => {
      expect(screen.getByText(/V5 65.5%/)).toBeDefined();
    });

    // 点击打开详情弹窗
    const button = screen.getByRole("button", { name: /NovelAI/i });
    fireEvent.click(button);

    expect(screen.getByText(/Opus/)).toBeDefined();
    expect(screen.getByText(/pst-...abcd/)).toBeDefined();
    expect(screen.getByText(/约 30 分钟/)).toBeDefined();

    // 点击刷新按钮
    const refreshBtn = screen.getByRole("button", { name: /刷新/ });
    fireEvent.click(refreshBtn);

    await waitFor(() => {
      expect(refreshSpy).toHaveBeenCalled();
      expect(screen.getByText(/V5 70.0%/)).toBeDefined();
    });
  });

  it("handles unconfigured token state", async () => {
    vi.spyOn(apiClient, "getNovelAIUsage").mockResolvedValue({
      configured: false,
      token_masked: "",
      active: false,
      tier: 0,
      tier_name: "None",
      anlas: 0,
      fixed_anlas: 0,
      purchased_anlas: 0,
      usage_percent: 0,
      time_until_next_percent: 0,
      unlimited_v5_eligible: false,
      error: "未配置 Token",
    });

    render(<NovelAIUsageBadge />);

    await waitFor(() => {
      expect(screen.getByText(/未配置/)).toBeDefined();
    });
  });
});
