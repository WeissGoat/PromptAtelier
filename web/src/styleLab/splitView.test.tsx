import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Recipe } from "./api";
import { SplitView } from "./SplitView";
import { tokenize } from "./tokens";

const PROMPT = "color trace, production art, 1girl, 这是一幅插画。少女站着, very aesthetic, masterpiece";

function recipe(): Recipe {
  return {
    schema: "tags-machine-core.style-lab.recipe/v1",
    id: "r1",
    name: "r",
    version: 1,
    created_at: 0,
    updated_at: 0,
    source_image_id: "img",
    group_id: null,
    stage: "split",
    locked: false,
    prefix: [],
    subject: tokenize(PROMPT).tokens.map((token, index) => ({ id: `s${index}`, text: token.text, sep: token.sep, origins: ["source"] })),
    suffix: [],
    dropped: [],
    character: { enabled: false, tokens: [], negative: [], add_male_caption: true },
    negative: [],
    model: null,
    params: {},
    use_source_vibe: false,
    flags: [],
    notes: "",
  };
}

/** 在显示原文的容器里按字符位置拖选（跨多个 span 也行）。 */
function dragSelect(start: number, end: number) {
  const root = screen.getByTestId("split-text");
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  let seen = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const length = node.textContent?.length ?? 0;
    if (start >= seen && start <= seen + length) range.setStart(node, start - seen);
    if (end >= seen && end <= seen + length) {
      range.setEnd(node, end - seen);
      break;
    }
    seen += length;
  }
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent.mouseUp(root);
}

afterEach(cleanup);

describe("split view", () => {
  it("marks dragged text as prefix or suffix and keeps the rest as subject", () => {
    const onCommit = vi.fn();
    render(<SplitView analysisReady={false} categories={{}} frequency={new Map()} onCommit={onCommit} recipe={recipe()} sourcePrompt={PROMPT} />);

    // 从半个词开始拖到句号后面：补全成整词，中文按选中的字切。
    const end = PROMPT.indexOf("。") + 1;
    dragSelect(3, end);
    expect(screen.getByText(/已选「color trace, production art, 1girl, 这是一幅插画。」/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /标为前缀/ }));

    // 1girl 拖选出来按 2 清掉标记，回主体。
    const girl = PROMPT.indexOf("1girl");
    dragSelect(girl, girl + 5);
    fireEvent.keyDown(window, { key: "2" });

    const tail = PROMPT.indexOf("very");
    dragSelect(tail, PROMPT.length);
    fireEvent.keyDown(window, { key: "3" });

    expect(screen.getByText("前缀 3")).toBeTruthy();
    expect(screen.getByText("后缀 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /锁定画风/ }));
    const committed = onCommit.mock.calls[0][0] as Recipe;
    expect(committed.prefix.map((token) => token.text)).toEqual(["color trace", "production art", "这是一幅插画。"]);
    expect(committed.subject.map((token) => token.text)).toEqual(["1girl", "少女站着"]);
    expect(committed.suffix.map((token) => token.text)).toEqual(["very aesthetic", "masterpiece"]);
    expect(committed.locked).toBe(true);
  });

  it("selects a whole mark on click so it can be changed", () => {
    const onCommit = vi.fn();
    const base = recipe();
    const marked = { ...base, prefix: base.subject.slice(0, 1), subject: base.subject.slice(1) };
    render(<SplitView analysisReady={false} categories={{}} frequency={new Map()} onCommit={onCommit} recipe={marked} sourcePrompt={PROMPT} />);
    expect(screen.getByText("前缀 1")).toBeTruthy();
    dragSelect(4, 4);
    expect(screen.getByText(/已选「color trace」/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /标为后缀/ }));
    expect(screen.getByText("前缀 0")).toBeTruthy();
    expect(screen.getByText("后缀 1")).toBeTruthy();
  });
});
