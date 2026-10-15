import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProbeRun, Recipe, RecipeToken } from "./api";

const api = vi.hoisted(() => ({
  getLibraryNode: vi.fn(),
  getShelf: vi.fn(),
  saveShelf: vi.fn(),
  startProbe: vi.fn(),
  getRecipeVersion: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<typeof import("./api")>()), ...api }));

import { resetShelfForTests } from "./materialShelf";
import { ablationUnits, orderedProbeItems, ProbePanel } from "./ProbePanel";
import { RecipeHistory } from "./RecipeHistory";
import { recipeDiff, restoreVersion, styleChanged } from "./recipeVersions";

function token(text: string, id = `t-${text}`): RecipeToken {
  return { id, text, sep: "", origins: ["source"] };
}

function recipe(overrides: Partial<Recipe> = {}): Recipe {
  return {
    schema: "tags-machine-core.style-lab.recipe/v1",
    id: "r1",
    name: "r",
    version: 3,
    created_at: 1,
    updated_at: 3,
    source_image_id: "img",
    group_id: null,
    stage: "edit",
    locked: true,
    prefix: [token("artist:foo"), token("flat color")],
    subject: [token("1girl"), token("sitting")],
    suffix: [token("very aesthetic")],
    dropped: [],
    character: { enabled: false, captions: [], add_male_caption: false },
    materials: [],
    negative: [],
    model: "nai-diffusion-4-5-full",
    params: { steps: 28 },
    use_source_vibe: false,
    flags: [],
    notes: "",
    ...overrides,
  };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  resetShelfForTests();
  api.getShelf.mockResolvedValue({ materials: [], facets: {} });
  api.saveShelf.mockImplementation((shelf: unknown) => Promise.resolve(shelf));
});

afterEach(cleanup);

describe("recipe versions", () => {
  it("lists token changes per zone and changed settings", () => {
    const before = recipe();
    const after = recipe({
      prefix: [token("artist:foo"), token("thick lines")],
      subject: [token("sitting"), token("1girl")],
      params: { steps: 23, sampler: "k_euler" },
      character: { enabled: true, captions: [{ tokens: [token("girl")], negative: [] }], add_male_caption: false },
    });
    const diff = recipeDiff(before, after);
    expect(diff.zones).toEqual([
      { label: "画风前缀", added: ["thick lines"], removed: ["flat color"] },
      { label: "角色提示词 #1", added: ["girl"], removed: [] },
    ]);
    expect(diff.fields.map((field) => field.label)).toEqual(["参数 sampler", "参数 steps", "启用角色提示词", "主体"]);
    expect(recipeDiff(before, { ...before, version: 9, updated_at: 99 }).same).toBe(true);

    const restored = restoreVersion(after, { ...before, version: 1, created_at: 0, updated_at: 0 });
    expect([restored.version, restored.created_at, restored.updated_at]).toEqual([3, 1, 3]);
    expect(restored.prefix).toEqual(before.prefix);
  });

  it("only counts style changes as a new version", () => {
    const before = recipe({ params: { steps: 28, sampler: "k_euler" } });
    const testOnly = recipe({
      name: "改名",
      subject: [token("sitting")],
      character: { enabled: true, captions: [{ tokens: [token("girl")], negative: [] }], add_male_caption: false },
      notes: "x",
      params: { sampler: "k_euler", steps: 28 },
    });
    expect(styleChanged(before, testOnly)).toBe(false);
    expect(styleChanged(before, recipe({ params: { steps: 23, sampler: "k_euler" } }))).toBe(true);
    expect(styleChanged(before, recipe({ params: before.params, prefix: [token("artist:foo")] }))).toBe(true);
    expect(styleChanged(before, recipe({ params: before.params, model: "nai-diffusion-5" }))).toBe(true);
  });

  it("shows what a save changed and restores an older version into the draft", async () => {
    const v2 = recipe({ version: 2, prefix: [token("artist:foo")] });
    const v1 = recipe({ version: 1, prefix: [] });
    api.getRecipeVersion.mockImplementation((_ws: string, _id: string, version: number) =>
      Promise.resolve({ recipe: version === 2 ? v2 : v1 }),
    );
    const onRestore = vi.fn();
    const current = recipe();
    render(
      <RecipeHistory
        dirty={false}
        exports={[{ folder: "a_Style", path: "", recipe_id: "r1", recipe_version: 2, recipe_name: "r", exported_at: 0, files: [], exists: true }]}
        history={[
          { version: 2, updated_at: 2 },
          { version: 1, updated_at: 1 },
        ]}
        onRestore={onRestore}
        runs={[]}
        saved={current}
        workspaceId="w"
      />,
    );
    expect(screen.getByText("导出 a_Style")).toBeTruthy();
    fireEvent.click(screen.getByText("v2"));
    // 默认看 v1 → v2 改了什么。
    expect(await screen.findByText("+ artist:foo")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /和当前比/ }));
    expect(await screen.findByText("+ flat color")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /恢复成 v2/ }));
    const restored = onRestore.mock.calls[0][0] as Recipe;
    expect(restored.version).toBe(3);
    expect(restored.prefix.map((item) => item.text)).toEqual(["artist:foo"]);
  });
});

describe("probe panel", () => {
  const props = {
    workspaceId: "w",
    dirty: false,
    source: null,
    runs: [] as ProbeRun[],
    onStarted: vi.fn(),
    onCancel: vi.fn(),
    onDropTokens: vi.fn(),
  };

  it("builds ablation units in recipe order, singly or together", () => {
    const draft = recipe();
    expect(ablationUnits(draft, ["t-very aesthetic", "t-artist:foo"], false)).toEqual([
      { label: "artist:foo", token_ids: ["t-artist:foo"] },
      { label: "very aesthetic", token_ids: ["t-very aesthetic"] },
    ]);
    expect(ablationUnits(draft, ["t-very aesthetic", "t-artist:foo"], true)).toEqual([
      { label: "artist:foo, very aesthetic", token_ids: ["t-artist:foo", "t-very aesthetic"] },
    ]);
  });

  it("orders ablation results by impact with the baseline first", () => {
    const item = (index: number, role: "baseline" | "variant", similarity?: number) => ({
      index,
      seed: 1,
      status: "succeeded" as const,
      label: String(index),
      role,
      baseline_compare: similarity === undefined ? undefined : { similarity, dhash_distance: 0 },
    });
    const run = { kind: "ablation", items: [item(0, "baseline"), item(1, "variant", 0.97), item(2, "variant", 0.8)] } as unknown as ProbeRun;
    expect(orderedProbeItems(run).map((entry) => entry.index)).toEqual([0, 2, 1]);
  });

  it("swaps in shelf characters with their filtered tags after saving", async () => {
    api.getShelf.mockResolvedValue({ materials: [{ role: "character", ref: "F:/角色/miku", name: "miku", excluded: ["twintails"] }], facets: {} });
    api.getLibraryNode.mockResolvedValue({
      ref: "F:/角色/miku",
      role: "character",
      name: "miku",
      has_preview: false,
      sections: [{ name: "hair", tags: ["aqua hair", "twintails"] }],
    });
    api.startProbe.mockResolvedValue({ run: { id: "run1" } });
    const draft = recipe();
    const onSave = vi.fn().mockResolvedValue(draft);
    render(<ProbePanel {...props} draft={draft} onSave={onSave} />);

    const button = screen.getByRole("button", { name: /生成 · 0 张/ });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(await screen.findByRole("checkbox", { name: /miku/ }));
    fireEvent.click(screen.getByRole("button", { name: /生成 · 1 张/ }));
    await waitFor(() => expect(api.startProbe).toHaveBeenCalled());
    expect(onSave).toHaveBeenCalled();
    const [, recipeId, settings] = api.startProbe.mock.calls[0];
    expect(recipeId).toBe("r1");
    expect(settings).toMatchObject({
      kind: "swap",
      characters: [{ ref: "F:/角色/miku", name: "miku", tags: ["aqua hair"] }],
      target: "auto",
      caption_index: null,
      include_baseline: false,
      seed_mode: "random",
    });
    expect(props.onStarted).toHaveBeenCalledWith({ id: "run1" });
  });

  it("ablates the picked style tokens with a baseline", async () => {
    api.startProbe.mockResolvedValue({ run: { id: "run2" } });
    const draft = recipe();
    render(<ProbePanel {...props} draft={draft} onSave={vi.fn().mockResolvedValue(draft)} />);
    fireEvent.click(screen.getByRole("radio", { name: "消融测试" }));
    fireEvent.click(screen.getByRole("button", { name: /flat color/ }));
    fireEvent.click(screen.getByRole("button", { name: /very aesthetic/ }));
    fireEvent.click(screen.getByRole("button", { name: /生成 · 3 张/ }));
    await waitFor(() => expect(api.startProbe).toHaveBeenCalled());
    expect(api.startProbe.mock.calls[0][2]).toMatchObject({
      kind: "ablation",
      include_baseline: true,
      units: [
        { label: "flat color", token_ids: ["t-flat color"] },
        { label: "very aesthetic", token_ids: ["t-very aesthetic"] },
      ],
    });
  });
});
