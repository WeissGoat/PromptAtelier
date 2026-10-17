import { describe, expect, it } from "vitest";

import type { Recipe, RecipeToken } from "./api";
import { compareRecipes, parseTag, zoneCounts } from "./recipeComparison";

function block(text: string): RecipeToken {
  return { id: `b-${text}`, text, sep: "", origins: ["source"] };
}

function recipe(overrides: Partial<Recipe> = {}): Recipe {
  return {
    schema: "tags-machine-core.style-lab.recipe/v1",
    id: "r",
    name: "r",
    version: 1,
    created_at: 0,
    updated_at: 0,
    source_image_id: null,
    group_id: null,
    stage: "edit",
    locked: true,
    prefix: [],
    subject: [],
    suffix: [],
    dropped: [],
    character: { enabled: false, captions: [], add_male_caption: false },
    negative: [],
    model: null,
    params: {},
    use_source_vibe: false,
    flags: [],
    notes: "",
    ...overrides,
  };
}

describe("recipe comparison", () => {
  it("reads weights from :: groups and braces", () => {
    expect(parseTag("0.6::ixy::")).toMatchObject({ key: "ixy", weight: 0.6 });
    expect(parseTag("{{Konya_Karasue}}")).toMatchObject({ key: "konya karasue", weight: 1.103 });
    expect(parseTag("0.9::cel rendering,anime coloring::")).toMatchObject({ key: "cel rendering, anime coloring", weight: 0.9 });
  });

  it("splits whole blocks into tags and marks weight changes, moves and one-sided tags", () => {
    const a = recipe({
      prefix: [block("0.6::ixy::, 0.9::keihh::, flat color")],
      suffix: [block("very aesthetic, masterpiece")],
    });
    const b = recipe({
      prefix: [block("0.8::ixy::, 0.9::keihh::, thick lines")],
      suffix: [block("masterpiece, flat color")],
    });
    const result = compareRecipes(a, b);
    const prefix = result.zones.find((zone) => zone.id === "prefix")!;
    expect(prefix.left.map((chip) => [chip.text, chip.status, chip.note ?? chip.movedTo])).toEqual([
      ["0.6::ixy::", "weight", "权重 0.6 → 0.8"],
      ["0.9::keihh::", "same", undefined],
      ["flat color", "moved", "画风后缀"],
    ]);
    expect(prefix.right.map((chip) => chip.status)).toEqual(["weight", "same", "only"]);
    expect(zoneCounts(prefix)).toEqual({ onlyLeft: 0, onlyRight: 1, weight: 1, moved: 1 });
    const suffix = result.zones.find((zone) => zone.id === "suffix")!;
    expect(suffix.left.map((chip) => chip.status)).toEqual(["only", "same"]);
    expect(suffix.right.map((chip) => [chip.text, chip.status])).toEqual([
      ["masterpiece", "same"],
      ["flat color", "moved"],
    ]);
    expect(result.styleSame).toBe(false);
  });

  it("treats separators and case as the same tag, order alone as a reorder", () => {
    const a = recipe({ prefix: [block("artist:foo, Flat_Color")], model: "m1" });
    const b = recipe({ prefix: [block("flat color,artist:foo")], model: "m2" });
    const result = compareRecipes(a, b);
    expect(result.zones[0]).toMatchObject({ changed: false, reordered: true });
    expect(result.fields.map((field) => field.label)).toEqual(["模型"]);
    expect(result.same).toBe(false);
  });
});
