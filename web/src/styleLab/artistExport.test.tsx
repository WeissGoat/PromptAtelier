import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtistExport, ArtistTestRun, ExportPreview, ImageRecord } from "./api";

const api = vi.hoisted(() => ({
  getExportDefaults: vi.fn(),
  previewExport: vi.fn(),
  exportArtist: vi.fn(),
  startArtistTest: vi.fn(),
  searchLibrary: vi.fn(),
}));

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return { ...actual, ...api };
});

import { ArtistTestPanel, meanSimilarity, regressionCandidates } from "./ArtistTestPanel";
import { DiffView, ExportDialog } from "./ExportDialog";

function image(id: string, overrides: Partial<ImageRecord> = {}): ImageRecord {
  return {
    id,
    path: `F:/x/${id}.png`,
    rel_path: `origin/${id}.png`,
    size_bytes: 1,
    mtime_ns: 1,
    post: { dir_name: id, date: "2026-01-01", post_id: id, title: null },
    width: 832,
    height: 1216,
    has_metadata: true,
    source_label: null,
    model: "nai-diffusion-4-5-full",
    request_type: "PromptGenerateRequest",
    prompt: "artist:foo, 1girl",
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
    ...overrides,
  };
}

const preview: ExportPreview = {
  folder: "1_Ink_v2",
  requested_folder: "1_Ink",
  exists: true,
  artist_root: "F:/design/画风",
  tags_txt: `artist:foo\n,\nmasterpiece\n=\ngen_json, {"x":"${"a".repeat(500)}"}\n`,
  files: ["tags.txt", "notes.md"],
  vibe_count: 0,
  roundtrip_ok: true,
  problems: [],
  warnings: [],
  candidates: ["1_Ink"],
  compare: {
    ref: "1_Ink",
    diff: {
      prefix: { added: ["artist:bar"], removed: [], same: false },
      suffix: { added: [], removed: [], same: true },
      negative: { added: [], removed: [], same: true },
      style: { added: ["artist:bar"], removed: [], same: false },
      params: [{ key: "scale", before: 5, after: 6 }],
      flags: null,
    },
  },
};

const exported: ArtistExport = {
  folder: "1_Ink",
  path: "F:/design/画风/1_Ink",
  recipe_id: "r",
  recipe_version: 2,
  recipe_name: "配方",
  exported_at: 1_700_000_000,
  files: ["tags.txt"],
  exists: true,
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
});

afterEach(() => {
  cleanup();
});

describe("regression candidates", () => {
  it("keeps one usable image per post, source first then newest", () => {
    const images = [
      image("a", { post: { dir_name: "a", date: "2026-01-01", post_id: "10", title: null } }),
      image("a2", { post: { dir_name: "a", date: "2026-01-01", post_id: "10", title: null } }),
      image("b", { post: { dir_name: "b", date: "2026-03-01", post_id: "11", title: null } }),
      image("c", { flags: ["inpaint"] }),
      image("d", { post: { dir_name: "d", date: "2025-01-01", post_id: "12", title: null } }),
      image("e", { has_metadata: false }),
    ];
    expect(regressionCandidates(images, null, "d").map((item) => item.id)).toEqual(["d", "b", "a"]);
    expect(regressionCandidates(images, ["a", "a2"], null).map((item) => item.id)).toEqual(["a"]);
  });

  it("averages similarity over finished items", () => {
    const run = {
      items: [
        { index: 0, seed: 1, status: "succeeded", compare: { similarity: 0.8 } },
        { index: 1, seed: 1, status: "succeeded", compare: { similarity: 0.9 } },
        { index: 2, seed: 1, status: "running" },
      ],
    } as unknown as ArtistTestRun;
    expect(meanSimilarity(run)).toBeCloseTo(0.85);
  });
});

describe("ExportDialog", () => {
  it("previews the target, diff and tags.txt, then exports to the previewed folder", async () => {
    api.getExportDefaults.mockResolvedValue({ author: "1", artist_root: "F:/design/画风", exports: [exported], candidates: ["1_Ink"] });
    api.previewExport.mockResolvedValue({ preview });
    api.exportArtist.mockResolvedValue({ export: { ...exported, folder: "1_Ink_v2" } });
    const onExported = vi.fn();
    render(<ExportDialog onClose={vi.fn()} onExported={onExported} recipeId="r" workspaceId="w" />);

    // 再次导出沿用上次的名字（去掉作者前缀），预览出并列版本。
    expect(await screen.findByText("1_Ink 已存在，导出为并列版本")).toBeTruthy();
    expect(api.previewExport).toHaveBeenCalledWith("w", "r", expect.objectContaining({ name: "Ink", author: "1" }));
    expect(screen.getByText(/读回校验通过/)).toBeTruthy();
    expect(screen.getByText("+ artist:bar")).toBeTruthy();
    expect(screen.getByText(/共 \d+ 字/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /导出到 1_Ink_v2/ }));
    await waitFor(() => expect(onExported).toHaveBeenCalled());
    expect(api.exportArtist).toHaveBeenCalledWith("w", "r", expect.objectContaining({ name: "Ink" }), "1_Ink_v2");
  });

  it("rejects names that are not english identifiers", async () => {
    api.getExportDefaults.mockResolvedValue({ author: null, artist_root: "F:/d", exports: [], candidates: [] });
    render(<ExportDialog onClose={vi.fn()} onExported={vi.fn()} recipeId="r" workspaceId="w" />);
    await waitFor(() => expect(api.getExportDefaults).toHaveBeenCalled());
    fireEvent.change(screen.getByPlaceholderText("Crisp_Manga_Ink"), { target: { value: "带 空格" } });
    expect(screen.getByText(/画风名只能用英文字母/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "导出" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.previewExport).not.toHaveBeenCalled();
  });

  it("explains a pure reorder", () => {
    render(
      <DiffView
        diff={{
          prefix: { added: [], removed: ["masterpiece"], same: false },
          suffix: { added: ["masterpiece"], removed: [], same: false },
          negative: { added: [], removed: [], same: true },
          style: { added: [], removed: [], same: false },
          params: [],
          flags: null,
        }}
      />,
    );
    expect(screen.getByText(/只是前后缀位置或顺序不同/)).toBeTruthy();
  });
});

describe("ArtistTestPanel", () => {
  const baseProps = {
    workspaceId: "w",
    recipeId: "r",
    recipeVersion: 3,
    dirty: false,
    groupImageIds: null,
    sourceImageId: "a",
    onExport: vi.fn(),
    onCancel: vi.fn(),
  };

  it("starts a regression run with the default picked images", async () => {
    const images = ["a", "b", "c", "d", "e"].map((id, index) =>
      image(id, { post: { dir_name: id, date: `2026-01-0${index + 1}`, post_id: id, title: null } }),
    );
    api.startArtistTest.mockResolvedValue({ run: { id: "run" } });
    const onStarted = vi.fn();
    render(<ArtistTestPanel {...baseProps} exports={[exported]} images={images} onStarted={onStarted} runs={[]} />);
    expect(screen.getByText("配方已更新到 v3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /用 1_Ink 生成 · 4 张/ }));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(api.startArtistTest).toHaveBeenCalledWith(
      "w",
      "r",
      expect.objectContaining({ kind: "regression", artist: "1_Ink", image_ids: ["a", "e", "d", "c"], seed_mode: "source" }),
    );
  });

  it("needs a character or action before a matrix run", () => {
    render(<ArtistTestPanel {...baseProps} exports={[exported]} images={[]} onStarted={vi.fn()} runs={[]} />);
    fireEvent.click(screen.getByRole("radio", { name: "泛化矩阵" }));
    expect((screen.getByRole("button", { name: /用 1_Ink 生成/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows only the export button before anything was exported", () => {
    render(<ArtistTestPanel {...baseProps} exports={[]} images={[]} onStarted={vi.fn()} runs={[]} />);
    expect(screen.getByText(/还没有导出过/)).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "回归对照" })).toBeNull();
  });
});
