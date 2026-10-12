import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageRecord, PostInfo } from "./api";
import { GroupPanel, groupImageIds, monthBuckets, postBuckets } from "./GroupPanel";

function image(id: string, post: PostInfo | null): ImageRecord {
  return {
    id,
    path: `F:/x/${id}.png`,
    rel_path: `origin/${id}.png`,
    size_bytes: 1,
    mtime_ns: 1,
    post,
    width: 832,
    height: 1216,
    has_metadata: true,
    source_label: null,
    model: "nai-diffusion-4-5-full",
    request_type: "PromptGenerateRequest",
    prompt: "1girl",
    negative_prompt: "",
    char_captions: [],
    seed: 1,
    steps: 28,
    scale: 5,
    cfg_rescale: 0,
    sampler: "k_euler_ancestral",
    noise_schedule: "karras",
    vibe: { count: 0, hashes: [], strengths: [], information_extracted: [] },
    flags: [],
  };
}

const post = (dir: string, date: string | null, title: string | null = null): PostInfo => ({
  dir_name: dir,
  date,
  post_id: dir,
  title,
});

const images = [
  image("a1", post("p1", "2026-08-30", "プロセカ")),
  image("a2", post("p1", "2026-08-30", "プロセカ")),
  image("b1", post("p2", "2026-09-01")),
  image("c1", post("p3", "2026-09-03", "プール")),
  image("d1", post("p4", null)),
];

afterEach(cleanup);

describe("post and month groups", () => {
  it("groups images by post in grid order and by month from early to late", () => {
    expect(postBuckets(images).map((bucket) => [bucket.name, bucket.sub, bucket.imageIds])).toEqual([
      ["プロセカ", "2026-08-30 · p1", ["a1", "a2"]],
      ["p2", "2026-09-01 · p2", ["b1"]],
      ["プール", "2026-09-03 · p3", ["c1"]],
      ["p4", "p4", ["d1"]],
    ]);
    expect(monthBuckets([images[4], ...images.slice(0, 4)]).map((bucket) => [bucket.name, bucket.posts, bucket.imageIds])).toEqual([
      ["2026 年 8 月", 1, ["a1", "a2"]],
      ["2026 年 9 月", 2, ["b1", "c1"]],
      ["没有日期", 1, ["d1"]],
    ]);
    // 拖进来的图片组没有投稿信息：不分投稿和月份。
    expect(postBuckets([image("x", null)])).toEqual([]);
    expect(monthBuckets([image("x", null)])).toEqual([]);
  });

  it("selects the images of a post or month bucket", () => {
    const months = monthBuckets(images);
    expect([...(groupImageIds(null, "month:2026-09", months) ?? [])]).toEqual(["b1", "c1"]);
    expect(groupImageIds(null, null, months)).toBeNull();
  });

  it("switches between style, post and month groups", () => {
    const onChangeMode = vi.fn();
    const onSelectGroup = vi.fn();
    const props = {
      analysis: null,
      llmAvailable: true,
      analyzing: null,
      postBuckets: postBuckets(images),
      monthBuckets: monthBuckets(images),
      selectedGroup: null,
      recipes: [],
      onChangeMode,
      onSelectGroup,
      onOpenRecipe: vi.fn(),
    };
    const { rerender } = render(<GroupPanel {...props} mode="style" />);
    fireEvent.click(screen.getByRole("radio", { name: "月份" }));
    expect(onChangeMode).toHaveBeenCalledWith("month");

    rerender(<GroupPanel {...props} mode="month" />);
    fireEvent.click(screen.getByRole("button", { name: /2026 年 9 月/ }));
    expect(onSelectGroup).toHaveBeenCalledWith("month:2026-09");

    rerender(<GroupPanel {...props} mode="post" />);
    expect(screen.getByRole("button", { name: /プール/ })).toBeTruthy();

    // 不是投稿文件夹时没有切换，只有画风分组。
    rerender(<GroupPanel {...props} mode="post" postBuckets={[]} monthBuckets={[]} />);
    expect(screen.queryByRole("radiogroup", { name: "分组方式" })).toBeNull();
    expect(screen.queryByRole("button", { name: /プール/ })).toBeNull();
  });
});
