import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompareWorkspaceProvider } from "../compare/CompareWorkspaceProvider";
import type { BaseTemplate, CompareRound, PromptVariant } from "../compare/types";
import { CompareRoundSection } from "./CompareRoundSection";

const template: BaseTemplate = {
  prompt: "1girl, solo",
  negative: "lowres",
  seed: 123456,
  width: 512,
  height: 512,
  steps: 28,
  scale: 5.0,
  sampler: "k_euler",
  model: "nai-diffusion-4-5-full",
};

const v1Idle: PromptVariant = {
  id: "v1",
  name: "变体 1-A",
  prompt: "1girl, solo, smile",
  diff: { added: ["smile"], removed: [], unchanged: ["1girl", "solo"], tokens: [] },
  seedOverride: null,
  status: "idle",
  jobId: null,
};

const v2Idle: PromptVariant = {
  id: "v2",
  name: "变体 1-B",
  prompt: "1girl, solo, blue eyes",
  diff: { added: ["blue eyes"], removed: [], unchanged: ["1girl", "solo"], tokens: [] },
  seedOverride: null,
  status: "idle",
  jobId: null,
};

const v1Succeeded: PromptVariant = {
  ...v1Idle,
  status: "succeeded",
  resultImage: {
    path: "outputs/v1.png",
    url: "/api/results/image?path=outputs%2Fv1.png",
    seed: 123456,
  },
};

const v2Succeeded: PromptVariant = {
  ...v2Idle,
  status: "succeeded",
  resultImage: {
    path: "outputs/v2.png",
    url: "/api/results/image?path=outputs%2Fv2.png",
    seed: 123456,
  },
};

describe("CompareRoundSection batch execution button", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  function renderSection(variants: PromptVariant[], onRunRound = vi.fn()) {
    const round: CompareRound = {
      id: "round-1",
      name: "第 1 批对比",
      template,
      basePrompt: template.prompt,
      variants,
      status: "idle",
    };

    render(
      <CompareWorkspaceProvider>
        <CompareRoundSection
          canDeleteRound={false}
          isBusy={false}
          onBatchDerive={vi.fn()}
          onOpenImageDetail={vi.fn()}
          onRunRound={onRunRound}
          onRunVariant={vi.fn()}
          onToggleSelectVariant={vi.fn()}
          round={round}
          selectedVariantIds={[]}
          template={template}
        />
      </CompareWorkspaceProvider>,
    );

    return { round, onRunRound };
  }

  it("shows '运行本批全部变体 (2)' when no variants have completed, and clicking runs all", () => {
    const onRunRound = vi.fn();
    renderSection([v1Idle, v2Idle], onRunRound);

    const runBtn = screen.getByRole("button", { name: /运行本批全部变体 \(2\)/ });
    expect(runBtn).toBeTruthy();
    expect(screen.queryByRole("button", { name: /重跑全部/ })).toBeNull();

    fireEvent.click(runBtn);
    expect(onRunRound).toHaveBeenCalledTimes(1);
    const passedVariants: PromptVariant[] = onRunRound.mock.calls[0][1];
    expect(passedVariants.map((v) => v.id)).toEqual(["v1", "v2"]);
  });

  it("shows '运行未完成变体 (1)' and '重跑全部 (2)' when some variants succeeded, and clicking '运行未完成变体' skips completed ones", () => {
    const onRunRound = vi.fn();
    // v1 is completed, v2 is idle
    renderSection([v1Succeeded, v2Idle], onRunRound);

    const runPendingBtn = screen.getByRole("button", { name: /运行未完成变体 \(1\)/ });
    const rerunAllBtn = screen.getByRole("button", { name: /重跑全部 \(2\)/ });

    expect(runPendingBtn).toBeTruthy();
    expect(rerunAllBtn).toBeTruthy();

    // Clicking "运行未完成变体" should only pass v2 (skipping v1)
    fireEvent.click(runPendingBtn);
    expect(onRunRound).toHaveBeenCalledTimes(1);
    const passedPending: PromptVariant[] = onRunRound.mock.calls[0][1];
    expect(passedPending.map((v) => v.id)).toEqual(["v2"]);

    // Clicking "重跑全部" should pass all runnable variants [v1, v2]
    fireEvent.click(rerunAllBtn);
    expect(onRunRound).toHaveBeenCalledTimes(2);
    const passedAll: PromptVariant[] = onRunRound.mock.calls[1][1];
    expect(passedAll.map((v) => v.id)).toEqual(["v1", "v2"]);
  });

  it("shows '重新运行全部变体 (2)' when all variants have completed", () => {
    const onRunRound = vi.fn();
    // Both v1 and v2 are completed
    renderSection([v1Succeeded, v2Succeeded], onRunRound);

    const rerunBtn = screen.getByRole("button", { name: /重新运行全部变体 \(2\)/ });
    expect(rerunBtn).toBeTruthy();
    expect(screen.queryByRole("button", { name: /运行未完成变体/ })).toBeNull();

    fireEvent.click(rerunBtn);
    expect(onRunRound).toHaveBeenCalledTimes(1);
    const passedVariants: PromptVariant[] = onRunRound.mock.calls[0][1];
    expect(passedVariants.map((v) => v.id)).toEqual(["v1", "v2"]);
  });
});
