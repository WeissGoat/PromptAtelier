import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "../api/client";
import type { ImageRecord, Recipe, RecipeToken } from "./api";
import { analyzeCommonality, diffAgainst, tagWeights } from "./commonality";
import { DuplicateNotice, duplicateOf } from "./DuplicateNotice";
import {
  addMaterial,
  addTokens,
  applyToCharacter,
  materialOrigin,
  removeMaterial,
  setMaterialTags,
  toggleMaterialTag,
} from "./recipeModel";

const api = vi.hoisted(() => ({ searchMaterials: vi.fn(), getLibraryNode: vi.fn(), getShelf: vi.fn(), saveShelf: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<typeof import("./api")>()), ...api }));

import { LibraryPanel } from "./LibraryPanel";
import { resetShelfForTests } from "./materialShelf";

function token(text: string, origins = ["source"]): RecipeToken {
  return { id: `t-${text}`, text, sep: "", origins };
}

function recipe(subject: string[] = ["1girl", "smile"]): Recipe {
  return {
    schema: "tags-machine-core.style-lab.recipe/v1",
    id: "r1",
    name: "r",
    version: 1,
    created_at: 0,
    updated_at: 0,
    source_image_id: "img",
    group_id: null,
    stage: "edit",
    locked: true,
    prefix: [],
    subject: subject.map((text) => token(text)),
    suffix: [],
    dropped: [],
    character: { enabled: false, captions: [], add_male_caption: false },
    materials: [],
    negative: [],
    model: null,
    params: {},
    use_source_vibe: false,
    flags: [],
    notes: "",
  };
}

function image(id: string, prompt: string, overrides: Partial<ImageRecord> = {}): ImageRecord {
  return {
    id,
    path: `F:/x/${id}.png`,
    rel_path: `${id}.png`,
    size_bytes: 1,
    mtime_ns: 1,
    post: null,
    width: 832,
    height: 1216,
    has_metadata: true,
    source_label: null,
    model: "nai-diffusion-4-5-full",
    request_type: null,
    prompt,
    negative_prompt: "lowres",
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

const miku = { role: "character" as const, ref: "F:/角色/miku", name: "miku", excluded: [] };
const origin = materialOrigin(miku);

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  resetShelfForTests();
  api.getShelf.mockResolvedValue({ materials: [], facets: {} });
  api.saveShelf.mockImplementation((shelf) => Promise.resolve(shelf));
});

afterEach(() => cleanup());

describe("material blocks", () => {
  it("adds a material as one block at a drop index, and replaces it in place when added again", () => {
    const next = addTokens(recipe(["1girl", "smile"]), ["aqua hair", "smile"], origin, 1);
    expect(next.added).toBe(1);
    expect(next.recipe.subject.map((item) => item.text)).toEqual(["1girl", "aqua hair, smile", "smile"]);
    expect(next.recipe.subject[1].origins).toEqual([origin]);
    const again = addTokens(next.recipe, ["aqua hair"], origin);
    expect(again.added).toBe(0);
    expect(again.recipe.subject.map((item) => item.text)).toEqual(["1girl", "aqua hair", "smile"]);
    expect(again.recipe.subject[1].id).toBe(next.recipe.subject[1].id);
  });

  it("filters tags and rewrites the applied block", () => {
    const all = ["aqua hair", "twintails"];
    let draft = addMaterial(recipe(), miku);
    draft = addTokens(draft, all, origin).recipe;
    draft = toggleMaterialTag(draft, origin, "twintails", all);
    expect(draft.materials![0].excluded).toEqual(["twintails"]);
    expect(draft.subject.map((item) => item.text)).toEqual(["1girl", "smile", "aqua hair"]);
    draft = toggleMaterialTag(draft, origin, "twintails", all);
    expect(draft.subject.map((item) => item.text)).toEqual(["1girl", "smile", "aqua hair, twintails"]);
    draft = setMaterialTags(draft, origin, all, false);
    expect(draft.subject.map((item) => item.text)).toEqual(["1girl", "smile"]);
  });

  it("puts a character block into the character prompt and removes everything with the block", () => {
    const all = ["aqua hair", "twintails"];
    let draft = addMaterial(recipe(), miku);
    const texts = (index: number) => draft.character.captions[index].tokens.map((item) => item.text);
    draft = applyToCharacter(draft, { origin, role: "character", tags: all });
    expect(draft.character.enabled).toBe(true);
    expect(texts(0)).toEqual(["girl, aqua hair, twintails"]);
    draft = applyToCharacter(draft, { origin: "action:x", role: "action", tags: ["sitting", "smile"] });
    expect(texts(0)).toEqual(["girl, aqua hair, twintails", "sitting, smile"]);
    // 放到第 2 条（还没有就新加）；筛掉 tag 时只改用到这块素材的那几条。
    draft = applyToCharacter(draft, { origin: "character:boy", role: "character", tags: ["boy", "tall"] }, 1);
    expect(texts(1)).toEqual(["boy, tall"]);
    draft = toggleMaterialTag(draft, origin, "aqua hair", all);
    expect(texts(0)).toEqual(["girl, twintails", "sitting, smile"]);
    expect(texts(1)).toEqual(["boy, tall"]);
    draft = toggleMaterialTag(draft, origin, "aqua hair", all);
    expect(texts(0)).toEqual(["girl, aqua hair, twintails", "sitting, smile"]);
    draft = addTokens(draft, ["aqua hair", "smile"], origin).recipe;
    draft = removeMaterial(draft, origin);
    expect(draft.materials).toEqual([]);
    expect(texts(0)).toEqual(["sitting, smile"]);
    expect(texts(1)).toEqual(["boy, tall"]);
    // 主体原有的 smile 保留，只去掉素材加的那一块。
    expect(draft.subject.map((item) => item.text)).toEqual(["1girl", "smile"]);
  });
});

describe("LibraryPanel", () => {
  it("picks onto the global shelf, filters there, and records the block in the recipe only when used", async () => {
    api.searchMaterials.mockResolvedValue({
      nodes: [{ role: "character", name: "miku", ref: "F:/角色/miku", relative: "vocaloid/miku", has_preview: false, copies: 2, copy_paths: ["a", "b"], facets: {} }],
      total: 1,
      has_more: false,
      facet_options: {},
    });
    api.getLibraryNode.mockResolvedValue({ ref: "F:/角色/miku", role: "character", name: "miku", has_preview: false, sections: [{ name: "hair", tags: ["aqua hair", "twintails"] }] });
    const onChange = vi.fn();
    render(<LibraryPanel draft={recipe()} onChange={onChange} translateOn={false} />);
    await waitFor(() => expect(api.getShelf).toHaveBeenCalled());

    fireEvent.focus(screen.getByRole("combobox"));
    const option = await screen.findByRole("option", { name: /miku/ });
    expect(screen.getByText(/合并 3 份/)).toBeTruthy();
    fireEvent.click(option);
    expect(screen.queryByRole("listbox")).toBeNull();
    const miku = { role: "character", ref: "F:/角色/miku", name: "miku", excluded: [] };
    await waitFor(() => expect(api.saveShelf).toHaveBeenLastCalledWith({ materials: [miku], facets: {} }));

    // 还没用进配方：筛 tag 只存到素材架，配方不变。
    fireEvent.click(await screen.findByRole("button", { name: /twintails/ }));
    await waitFor(() =>
      expect(api.saveShelf).toHaveBeenLastCalledWith({ materials: [{ ...miku, excluded: ["twintails"] }], facets: {} }),
    );
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /加入主体/ }));
    const added = onChange.mock.calls[0][0] as Recipe;
    expect(added.materials).toEqual([{ ...miku, excluded: ["twintails"] }]);
    expect(added.subject.map((item) => item.text)).toEqual(["1girl", "smile", "aqua hair"]);

    // 只有标题栏能拖，tag 区可以拖选复制：复制出来的是 tag 本身，逗号分隔，拖选松手不算点击。
    const card = screen.getByRole("button", { name: /aqua hair/ }).closest("article")!;
    expect(card.getAttribute("draggable")).toBeNull();
    expect(card.querySelector("header")!.getAttribute("draggable")).toBe("true");
    const range = document.createRange();
    range.selectNodeContents(card.querySelector(".sl-card-section")!);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);
    const setData = vi.fn();
    fireEvent.copy(card, { clipboardData: { setData } });
    expect(setData).toHaveBeenCalledWith("text/plain", "aqua hair, twintails");
    const saves = api.saveShelf.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /aqua hair/ }));
    expect(api.saveShelf.mock.calls.length).toBe(saves);
    window.getSelection()!.removeAllRanges();
  });

  it("keeps the shelf and the action filters when another recipe opens", async () => {
    api.getShelf.mockResolvedValue({
      materials: [{ role: "action", ref: "F:/动作/sit", name: "sit", excluded: ["chair"] }],
      facets: { action: { cast: "solo" } },
    });
    api.searchMaterials.mockResolvedValue({ nodes: [], total: 0, has_more: false, facet_options: {} });
    api.getLibraryNode.mockResolvedValue({ ref: "F:/动作/sit", role: "action", name: "sit", has_preview: false, sections: [{ name: "pose", tags: ["sitting", "chair"] }] });
    render(<LibraryPanel draft={{ ...recipe(), id: "other" }} onChange={vi.fn()} translateOn={false} />);
    fireEvent.click(screen.getByRole("tab", { name: /动作/ }));
    expect(await screen.findByText("sit")).toBeTruthy();
    expect((await screen.findByRole("button", { name: /chair/ })).getAttribute("aria-pressed")).toBe("false");
    await waitFor(() => expect(api.searchMaterials).toHaveBeenLastCalledWith("action", "", { cast: "solo" }, { limit: 30 }));
    expect((screen.getByLabelText("按人数筛选") as HTMLSelectElement).value).toBe("solo");
  });

  it("asks which character prompt a card goes into when there are several", async () => {
    api.getShelf.mockResolvedValue({ materials: [{ role: "character", ref: "F:/角色/nahida", name: "nahida", excluded: [] }], facets: {} });
    api.searchMaterials.mockResolvedValue({ nodes: [], total: 0, has_more: false, facet_options: {} });
    api.getLibraryNode.mockResolvedValue({ ref: "F:/角色/nahida", role: "character", name: "nahida", has_preview: false, sections: [{ name: "hair", tags: ["green hair"] }] });
    const caption = (text: string) => ({ tokens: [token(text)], negative: [] });
    const draft = { ...recipe(), character: { enabled: true, captions: [caption("girl, sandrone"), caption("girl, columbina"), caption("boy, aether")], add_male_caption: false } };
    const onChange = vi.fn();
    render(<LibraryPanel draft={draft} onChange={onChange} translateOn={false} />);
    fireEvent.click(screen.getByRole("tab", { name: /角色/ }));
    const select = (await screen.findByLabelText("nahida 作角色提示词")) as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    expect([...select.options].map((option) => option.textContent)).toEqual([
      "作角色提示词…",
      "替换 #1：girl, sandrone",
      "替换 #2：girl, columbina",
      "替换 #3：boy, aether",
      "新加一条 #4",
    ]);
    // 选第 2 条：只换第 2 条，第 1 条不被覆盖。
    fireEvent.change(select, { target: { value: "1" } });
    const next = onChange.mock.calls[0][0] as Recipe;
    expect(next.character.captions.map((item) => item.tokens.map((block) => block.text).join(" | "))).toEqual([
      "girl, sandrone",
      "girl, green hair",
      "boy, aether",
    ]);
  });

  it("filters actions by facet", async () => {
    api.searchMaterials.mockResolvedValue({ nodes: [], total: 0, has_more: false, facet_options: { cast: [{ value: "solo", count: 3 }] } });
    render(<LibraryPanel draft={recipe()} onChange={vi.fn()} translateOn={false} />);
    fireEvent.click(screen.getByRole("tab", { name: /动作/ }));
    const select = await screen.findByLabelText("按人数筛选");
    await waitFor(() => expect(screen.getByRole("option", { name: "单人 · 3" })).toBeTruthy());
    fireEvent.change(select, { target: { value: "solo" } });
    await waitFor(() => expect(api.searchMaterials).toHaveBeenLastCalledWith("action", "", { cast: "solo" }, { limit: 30 }));
  });
});

describe("commonality", () => {
  it("splits tags into tiers, notices mixed weights and recommends the most central image", () => {
    const result = analyzeCommonality([
      image("a", "0.6::ixy::, 1girl, smile, outdoors", { scale: 5 }),
      image("b", "0.9::ixy::, 1girl, smile, night", { scale: 5 }),
      image("c", "0.6::ixy::, 1girl, cat ears", { scale: 6 }),
      image("x", "", { has_metadata: false }),
    ]);
    expect(result.count).toBe(3);
    expect(result.prompt.all.map((stat) => stat.tag)).toEqual(["1girl", "ixy"]);
    expect([...result.prompt.all[1].weights.keys()].sort()).toEqual(["0.6", "0.9"]);
    expect(result.prompt.most.map((stat) => stat.tag)).toEqual(["smile"]);
    const cfg = result.params.find((param) => param.key === "scale")!;
    expect(cfg.consistent).toBe(false);
    expect(cfg.majority).toBe("5");
    const c = result.profiles.find((profile) => profile.image.id === "c")!;
    expect(c.missing).toEqual(["smile"]);
    expect(c.unique).toEqual(["cat ears"]);
    expect(c.deviations).toEqual([{ label: "CFG", value: "6", majority: "5" }]);
    expect(result.profiles[0].image.id).not.toBe("c");
  });

  it("diffs one image against the majority or against one other image, ignoring size", () => {
    const a = image("a", "0.6::ixy::, 1girl, smile, outdoors", { scale: 6, width: 1216, height: 832 });
    const b = image("b", "0.9::ixy::, 1girl, smile, night");
    const c = image("c", "0.9::ixy::, 1girl, cat ears");
    const majority = diffAgainst(a, [a, b, c]);
    expect(majority.others).toBe(2);
    expect(majority.prompt.added).toEqual(["outdoors"]);
    expect(majority.prompt.missing).toEqual([]);
    expect(majority.prompt.weights).toEqual([{ tag: "ixy", mine: "0.6", theirs: "0.9" }]);
    expect(majority.params).toEqual([{ label: "CFG", mine: "6", theirs: "5" }]);

    const pair = diffAgainst(a, [c]);
    expect(pair.prompt.added).toEqual(["smile", "outdoors"]);
    expect(pair.prompt.missing).toEqual(["cat ears"]);
    expect(analyzeCommonality([a, b, c]).params.some((param) => param.label === "尺寸")).toBe(false);
  });

  it("reads leading numeric weights", () => {
    expect(Object.fromEntries(tagWeights("0.6::ixy::, -2::sketch::, smile"))).toEqual({ ixy: "0.6", sketch: "-2", smile: "1" });
    expect(Object.fromEntries(tagWeights("2.4::oekaki,:: -2::sketch, jaggy lines,::, 0.9::cel rendering,anime coloring::"))).toEqual({
      oekaki: "2.4",
      sketch: "-2",
      "jaggy lines": "-2",
      "cel rendering": "0.9",
      "anime coloring": "0.9",
    });
  });
});

describe("duplicate requests", () => {
  it("recognises the 409 and offers to force", () => {
    const error = new ApiClientError("dup", { status: 409, code: "duplicate_request", details: { run_id: "r1", status: "succeeded", created_at: 1_700_000_000 } });
    const duplicate = duplicateOf(error)!;
    expect(duplicate).toEqual({ runId: "r1", status: "succeeded", createdAt: 1_700_000_000 });
    expect(duplicateOf(new Error("x"))).toBeNull();
    const onForce = vi.fn();
    render(<DuplicateNotice duplicate={duplicate} onDismiss={vi.fn()} onForce={onForce} />);
    expect(screen.getByText(/已经出完/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "仍要生成" }));
    expect(onForce).toHaveBeenCalled();
  });
});
