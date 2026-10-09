import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageRecord } from "./api";
import { modelLabel, vibeKey, vibeLabel } from "./format";
import { emptyFilters, filterImages } from "./ImageBrowser";
import { defaultRegenSettings, RegenPanel } from "./RegenPanel";
import { splitPromptTags } from "./translations";

function image(overrides: Partial<ImageRecord>): ImageRecord {
  return {
    id: "a",
    path: "F:/x/a.png",
    rel_path: "origin/2026-01-11_1_t/a.png",
    size_bytes: 1,
    mtime_ns: 1,
    post: { dir_name: "2026-01-11_1_t", date: "2026-01-11", post_id: "1", title: "t" },
    width: 832,
    height: 1216,
    has_metadata: true,
    source_label: null,
    model: "nai-diffusion-4-5-full",
    request_type: "PromptGenerateRequest",
    prompt: "artist:foo, 1girl, solo",
    negative_prompt: "lowres",
    char_captions: [],
    seed: 42,
    steps: 28,
    scale: 5,
    cfg_rescale: 0,
    sampler: "k_euler_ancestral",
    noise_schedule: "karras",
    vibe: { count: 0, hashes: [], strengths: [], information_extracted: [] },
    flags: [],
    ...overrides,
  };
}

describe("style lab helpers", () => {
  it("formats model names", () => {
    expect(modelLabel("nai-diffusion-4-5-full")).toBe("V4.5 Full");
    expect(modelLabel("nai-diffusion-3")).toBe("V3");
    expect(modelLabel("nai-diffusion-4-5-full-inpainting")).toBe("V4.5 Full 重绘");
    expect(modelLabel(null)).toBe("未知模型");
  });

  it("keys vibe groups by hash list", () => {
    const withVibe = image({ vibe: { count: 2, hashes: ["86b3d31d", "06fdaaaa"], strengths: [0.4, 0.4], information_extracted: [1, 1] } });
    expect(vibeKey(withVibe)).toBe("86b3d31d+06fdaaaa");
    expect(vibeLabel(vibeKey(withVibe))).toBe("vibe 86b3+06fd");
    expect(vibeLabel(vibeKey(image({})))).toBe("无 vibe");
  });

  it("splits prompts like the backend", () => {
    expect(splitPromptTags("no text, best quality|ame(uten cancel)|[[akipeko]]\n, solo")).toEqual([
      "no text",
      "best quality",
      "ame(uten cancel)",
      "[[akipeko]]",
      "solo",
    ]);
  });

  it("filters by model, flags, special images and query", () => {
    const images = [
      image({ id: "a" }),
      image({ id: "b", model: "nai-diffusion-3", prompt: "1boy" }),
      image({ id: "c", flags: ["inpaint"] }),
      image({ id: "d", flags: ["no_metadata"], has_metadata: false, prompt: "" }),
    ];
    const ids = (filters: typeof emptyFilters) => filterImages(images, filters).map((item) => item.id);
    expect(ids(emptyFilters)).toEqual(["a", "b", "c", "d"]);
    expect(ids({ ...emptyFilters, models: ["nai-diffusion-3"] })).toEqual(["b"]);
    expect(ids({ ...emptyFilters, flags: ["inpaint"] })).toEqual(["c"]);
    expect(ids({ ...emptyFilters, hideSpecial: true })).toEqual(["a", "b"]);
    expect(ids({ ...emptyFilters, query: "1BOY" })).toEqual(["b"]);
  });
});

describe("RegenPanel", () => {
  afterEach(() => cleanup());

  it("blocks submit when a fixed seed is missing", () => {
    const onSubmit = vi.fn();
    render(
      <RegenPanel
        error={null}
        image={image({})}
        onChange={() => undefined}
        onSubmit={onSubmit}
        settings={{ ...defaultRegenSettings, seed_mode: "fixed" }}
        submitting={false}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /原参重生/ }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("填写种子，或改用原图 / 随机种子。")).toBeTruthy();
  });

  it("submits with source settings and shows the source seed", () => {
    const onSubmit = vi.fn();
    render(
      <RegenPanel
        error={null}
        image={image({})}
        onChange={() => undefined}
        onSubmit={onSubmit}
        settings={defaultRegenSettings}
        submitting={false}
      />,
    );
    expect(screen.getByRole("radio", { name: "原图 42" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "原参重生 · 1 张" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("disables regenerate for images without metadata", () => {
    render(
      <RegenPanel
        error={null}
        image={image({ has_metadata: false })}
        onChange={() => undefined}
        onSubmit={() => undefined}
        settings={defaultRegenSettings}
        submitting={false}
      />,
    );
    expect((screen.getByRole("button", { name: /原参重生/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});
