import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "../api/client";
import type { ImageRecord, Recipe, RecipeToken } from "./api";
import { analyzeCommonality, tagWeights } from "./commonality";
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

const api = vi.hoisted(() => ({ searchMaterials: vi.fn(), getLibraryNode: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<typeof import("./api")>()), ...api }));

import { LibraryPanel } from "./LibraryPanel";

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
    character: { enabled: false, tokens: [], negative: [], add_male_caption: false },
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
});

afterEach(() => cleanup());

describe("material blocks", () => {
  it("adds at a drop index and keeps existing tags as shared sources", () => {
    const next = addTokens(recipe(["1girl", "smile"]), ["aqua hair", "smile"], origin, 1).recipe;
    expect(next.subject.map((item) => item.text)).toEqual(["1girl", "aqua hair", "smile"]);
    expect(next.subject[2].origins).toEqual(["source", origin]);
  });

  it("filters tags and keeps the applied subject in sync", () => {
    let draft = addMaterial(recipe(), miku);
    draft = addTokens(draft, ["aqua hair", "twintails"], origin).recipe;
    draft = toggleMaterialTag(draft, origin, "twintails");
    expect(draft.materials![0].excluded).toEqual(["twintails"]);
    expect(draft.subject.map((item) => item.text)).toEqual(["1girl", "smile", "aqua hair"]);
    draft = toggleMaterialTag(draft, origin, "twintails");
    expect(draft.subject.map((item) => item.text)).toContain("twintails");
    draft = setMaterialTags(draft, origin, ["aqua hair", "twintails"], false);
    expect(draft.subject.map((item) => item.text)).toEqual(["1girl", "smile"]);
  });

  it("puts a character block into the character prompt and removes everything with the block", () => {
    let draft = addMaterial(recipe(), miku);
    draft = applyToCharacter(draft, { origin, role: "character", tags: ["aqua hair"] });
    expect(draft.character.enabled).toBe(true);
    expect(draft.character.tokens.map((item) => item.text)).toEqual(["girl", "aqua hair"]);
    draft = applyToCharacter(draft, { origin: "action:x", role: "action", tags: ["sitting"] });
    expect(draft.character.tokens.map((item) => item.text)).toEqual(["girl", "aqua hair", "sitting"]);
    draft = addTokens(draft, ["aqua hair", "smile"], origin).recipe;
    draft = removeMaterial(draft, origin);
    expect(draft.materials).toEqual([]);
    expect(draft.character.tokens.map((item) => item.text)).toEqual(["sitting"]);
    // 主体原有的 smile 保留，只去掉素材加的。
    expect(draft.subject.map((item) => item.text)).toEqual(["1girl", "smile"]);
  });
});

describe("LibraryPanel", () => {
  it("picks from the dropdown into a persistent block, then adds the filtered tags", async () => {
    api.searchMaterials.mockResolvedValue({
      nodes: [{ role: "character", name: "miku", ref: "F:/角色/miku", relative: "vocaloid/miku", has_preview: false, copies: 2, copy_paths: ["a", "b"], facets: {} }],
      total: 1,
      has_more: false,
      facet_options: {},
    });
    api.getLibraryNode.mockResolvedValue({ ref: "F:/角色/miku", role: "character", name: "miku", has_preview: false, sections: [{ name: "hair", tags: ["aqua hair", "twintails"] }] });
    const onChange = vi.fn();
    const view = render(<LibraryPanel draft={recipe()} onChange={onChange} translateOn={false} />);

    fireEvent.focus(screen.getByRole("combobox"));
    const option = await screen.findByRole("option", { name: /miku/ });
    expect(screen.getByText(/合并 3 份/)).toBeTruthy();
    fireEvent.click(option);
    expect(screen.queryByRole("listbox")).toBeNull();
    const picked = onChange.mock.calls[0][0] as Recipe;
    expect(picked.materials).toEqual([{ role: "character", ref: "F:/角色/miku", name: "miku", excluded: [] }]);

    view.rerender(<LibraryPanel draft={picked} onChange={onChange} translateOn={false} />);
    fireEvent.click(await screen.findByRole("button", { name: /twintails/ }));
    const filtered = onChange.mock.calls[1][0] as Recipe;
    expect(filtered.materials![0].excluded).toEqual(["twintails"]);

    view.rerender(<LibraryPanel draft={filtered} onChange={onChange} translateOn={false} />);
    fireEvent.click(screen.getByRole("button", { name: /加入主体/ }));
    const added = onChange.mock.calls[2][0] as Recipe;
    expect(added.subject.map((item) => item.text)).toEqual(["1girl", "smile", "aqua hair"]);
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

  it("reads leading numeric weights", () => {
    expect(Object.fromEntries(tagWeights("0.6::ixy::, -2::sketch::, smile"))).toEqual({ ixy: "0.6", sketch: "-2", smile: "1" });
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
