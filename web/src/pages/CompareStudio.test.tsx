import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { CompareStudio } from "./CompareStudio";

describe("CompareStudio", () => {
  beforeAll(() => {
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
  });

  function clickAddRound() {
    const btn = screen.getByRole("button", { name: /往下新增新的一批对比/ });
    fireEvent.click(btn);
  }

  it("renders template bar with dropzone instructions", () => {
    render(<CompareStudio />);

    expect(screen.getByText(/拖拽 PNG 图片至此处/)).toBeTruthy();
    expect(screen.getByText(/读入参数生成模板/)).toBeTruthy();
  });

  it("renders '往下新增新的一批对比' button", () => {
    render(<CompareStudio />);

    const addRoundButton = screen.getByRole("button", {
      name: /往下新增新的一批对比/,
    });
    expect(addRoundButton).toBeTruthy();
  });

  it("allows clicking add round to create a new round section", () => {
    render(<CompareStudio />);

    clickAddRound();

    expect(screen.getAllByText("第 1 批对比").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByDisplayValue("变体 1-A")).toBeTruthy();

    const clearButton = screen.getByRole("button", {
      name: /清空工作区/,
    });
    fireEvent.click(clearButton);

    expect(screen.queryByText("第 1 批对比")).toBeNull();
  });

  it("allows deleting a round when multiple rounds exist", () => {
    render(<CompareStudio />);

    clickAddRound(); // Round 1
    clickAddRound(); // Round 2

    expect(screen.getAllByText("第 1 批对比").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("第 2 批对比").length).toBeGreaterThanOrEqual(1);

    const deleteButtons = screen.getAllByRole("button", { name: /删除整批/ });
    expect(deleteButtons.length).toBe(2);

    // Delete Round 2
    fireEvent.click(deleteButtons[1]);

    expect(screen.getAllByText("第 1 批对比").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("第 2 批对比")).toBeNull();

    // Now only Round 1 remains, canDeleteRound is false, so delete button disappears
    expect(screen.queryByRole("button", { name: /删除整批/ })).toBeNull();
  });

  it("renders left batch index sidebar and allows quick switching", () => {
    render(<CompareStudio />);

    clickAddRound(); // Round 1
    clickAddRound(); // Round 2

    const sidebar = screen.getByTestId("compare-index-sidebar");
    expect(sidebar).toBeTruthy();
    expect(screen.getByText("批次索引")).toBeTruthy();
    expect(sidebar.querySelector(".sidebar-count-badge")?.textContent).toContain("2 批");

    // Clicking sidebar item scrolls into view
    const roundItems = screen.getAllByText(/#1/);
    expect(roundItems.length).toBeGreaterThanOrEqual(1);
    fireEvent.click(roundItems[0]);
  });

  it("allows deriving a new round downwards directly from sidebar", () => {
    render(<CompareStudio />);

    clickAddRound(); // Round 1
    clickAddRound(); // Round 2

    const sidebar = screen.getByTestId("compare-index-sidebar");
    expect(sidebar.querySelector(".sidebar-count-badge")?.textContent).toContain("2 批");

    // Click "向下派生" on Round 1 in sidebar
    const deriveButtons = screen.getAllByRole("button", { name: /向下派生/ });
    expect(deriveButtons.length).toBeGreaterThanOrEqual(2);

    // Derive downward from round 1
    fireEvent.click(deriveButtons[0]);

    // Should now have 3 rounds, and newly derived round is inserted between round 1 and round 2
    expect(sidebar.querySelector(".sidebar-count-badge")?.textContent).toContain("3 批");
  });

  it("allows reordering rounds via sidebar up and down buttons", () => {
    render(<CompareStudio />);

    clickAddRound(); // Round 1
    clickAddRound(); // Round 2

    const downButtons = screen.getAllByRole("button", { name: /下移批次/ });
    expect(downButtons.length).toBe(2);
    // First round can move down
    expect(downButtons[0].hasAttribute("disabled")).toBe(false);
    // Last round cannot move down
    expect(downButtons[1].hasAttribute("disabled")).toBe(true);

    // Move Round 1 down
    fireEvent.click(downButtons[0]);

    // Verify reordering took effect
    const upButtons = screen.getAllByRole("button", { name: /上移批次/ });
    // First item now cannot move up
    expect(upButtons[0].hasAttribute("disabled")).toBe(true);
  });

  it("allows collapsing and expanding sidebar", () => {
    render(<CompareStudio />);

    clickAddRound();

    const collapseButton = screen.getByRole("button", { name: /折叠批次索引/ });
    fireEvent.click(collapseButton);

    expect(screen.getByRole("button", { name: /展开批次索引/ })).toBeTruthy();

    const expandButton = screen.getByRole("button", { name: /展开批次索引/ });
    fireEvent.click(expandButton);

    expect(screen.getByText("批次索引")).toBeTruthy();
  });

  it("preserves first base-identical variant as control group and skips subsequent duplicates", () => {
    render(<CompareStudio />);

    clickAddRound(); // Creates Round 1 with Variant 1-A (which has base prompt, identical to base)

    // Variant 1-A is identical to base template, but acts as the control group (对照组), so it is runnable!
    expect(screen.getByText("对照组 (与基准一致)")).toBeTruthy();
    const runBatchBtn = screen.getByRole("button", { name: /运行本批全部变体 \(1\)/ });
    expect(runBatchBtn).toBeTruthy();
    expect(runBatchBtn.hasAttribute("disabled")).toBe(false);

    // Click "+ 新增横向变体" to add Variant 1-B (initial prompt is base prompt, identical to base)
    const addVarBtn = screen.getByText("新增横向变体");
    fireEvent.click(addVarBtn);

    // Total variants = 2. Variant 1-A is control group, but Variant 1-B duplicates control group, so runnable count remains 1!
    expect(screen.getByRole("button", { name: /运行本批全部变体 \(1\)/ })).toBeTruthy();
    expect(screen.getByText("与对照组重复 (跳过)")).toBeTruthy();

    // Now edit Variant 1-B to something unique ("1girl, solo, glasses")
    const allPromptInputs = screen.getAllByLabelText("变体提示词");
    expect(allPromptInputs.length).toBe(2);
    fireEvent.change(allPromptInputs[1], { target: { value: "1girl, solo, glasses" } });

    // Now both variants are runnable (Variant 1-A control group + Variant 1-B unique diff), count is 2!
    expect(screen.getByRole("button", { name: /运行本批全部变体 \(2\)/ })).toBeTruthy();

    // Now edit Variant 1-A to the same prompt as Variant 1-B ("1girl, solo, glasses")
    fireEvent.change(allPromptInputs[0], { target: { value: "1girl, solo, glasses" } });

    // Now Variant 1-B is a duplicate of Variant 1-A (both non-base identical), runnable count drops back to 1!
    expect(screen.getByRole("button", { name: /运行本批全部变体 \(1\)/ })).toBeTruthy();
    expect(screen.getByText("与同批变体重复 (跳过)")).toBeTruthy();
  });

  it("opens BatchDeriveDialog from round action and derives multiple rounds", async () => {
    const mockInspectResponse = {
      filename: "summer_beach.png",
      dimensions: { width: 1024, height: 1024 },
      prompt: "beach, ocean, sunny day",
      negative_prompt: "worst quality",
      seed: 999111,
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

    render(<CompareStudio />);
    clickAddRound(); // Creates Round 1

    expect(screen.getAllByText("第 1 批对比").length).toBeGreaterThanOrEqual(1);

    // Click "多图批量派生..." button
    const batchDeriveBtn = screen.getByRole("button", { name: /多图批量派生/ });
    fireEvent.click(batchDeriveBtn);

    // Dialog opens
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText(/多图批量派生新批次/)).toBeTruthy();

    // Upload an image
    const file = new File(["test data"], "summer_beach.png", { type: "image/png" });
    const fileInput = screen.getByRole("dialog").querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    // Wait for card to be ready
    await waitFor(() => {
      expect(screen.getByText("1024×1024")).toBeTruthy();
    });

    // Uncheck autoRun for test simplicity
    const autoRunCheckbox = screen.getByRole("checkbox");
    fireEvent.click(autoRunCheckbox);

    // Confirm batch derive
    const confirmBtn = screen.getByRole("button", { name: /确定派生 1 个新批次/ });
    fireEvent.click(confirmBtn);

    // Dialog should close and new round should appear
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    expect(screen.getAllByText("第 1 批对比 - summer_beach").length).toBeGreaterThanOrEqual(1);
  });
});

