import { describe, expect, it } from "vitest";

import type { ImageRecord, Recipe, RecipeToken } from "./api";
import {
  addTokens,
  applyCuts,
  applySuggestions,
  commitSplit,
  cutsOf,
  moveTokens,
  placeToken,
  postFrequency,
  removeOrigin,
  restoreSourceSubject,
  retokenize,
  splitStateOf,
  suggestZones,
  tokenCategory,
  tokensToText,
} from "./recipeModel";
import { tokenize } from "./tokens";

function tokens(text: string): RecipeToken[] {
  return tokenize(text).tokens.map((token, index) => ({ id: `s${index}`, text: token.text, sep: token.sep, origins: ["source"] }));
}

function recipe(subject: string): Recipe {
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
    subject: tokens(subject),
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

const texts = (list: RecipeToken[]) => list.map((token) => token.text);

describe("split stage", () => {
  it("cuts the stream into prefix, subject and suffix", () => {
    const base = recipe("shirabi|[[akipeko]], 1girl, sitting, smooth shading, best quality");
    let state = splitStateOf(base);
    state = applyCuts(state, 2, 4);
    expect(cutsOf(state)).toEqual([2, 4]);
    const committed = commitSplit(base, state);
    expect(texts(committed.prefix)).toEqual(["shirabi", "[[akipeko]]"]);
    expect(texts(committed.subject)).toEqual(["1girl", "sitting"]);
    expect(texts(committed.suffix)).toEqual(["smooth shading", "best quality"]);
    expect(committed.stage).toBe("edit");
    expect(committed.locked).toBe(true);
    // 竖线分隔符保留在 token 上，前缀拼回去和原文一致。
    expect(tokensToText(committed.prefix)).toBe("shirabi|[[akipeko]]");
  });

  it("suggests zones from categories and group frequency", () => {
    const base = recipe(
      "eye-level, artist:foo, shallow depth of field, aoi sora, 1girl, smirk, white dress, ink painting, blush, best quality",
    );
    const categories = {
      "eye-level": "camera",
      "shallow depth of field": "camera",
      "aoi sora": "character",
      "1girl": "count",
      smirk: "expression",
      "white dress": "clothing",
      "ink painting": "style",
      blush: "expression",
      "best quality": "quality",
    } as const;
    const frequency = new Map([
      ["shallow depth of field", 1],
      ["aoi sora", 1],
      ["1girl", 1],
      ["eye-level", 0.3],
      ["ink painting", 0.2],
      ["best quality", 0.9],
    ]);
    const suggestions = suggestZones(base.subject, categories, frequency);
    const zoneOf = (text: string) => suggestions[base.subject.find((token) => token.text === text)!.id].zone;
    // 画风栈前面只有一个镜头词、后面是大部分内容：进前缀。
    expect(zoneOf("artist:foo")).toBe("prefix");
    // 高频镜头词可能是画风调味也可能是内容：不自动划分，标为待判断。
    expect(zoneOf("shallow depth of field")).toBeNull();
    expect(suggestions[base.subject.find((token) => token.text === "shallow depth of field")!.id].review).toBe(true);
    expect(zoneOf("eye-level")).toBe("subject");
    // 高频的 1girl 仍是主体；高频作品名拿不准；低频风格词拿不准。
    expect(zoneOf("1girl")).toBe("subject");
    expect(zoneOf("aoi sora")).toBeNull();
    expect(zoneOf("ink painting")).toBeNull();
    // 最后的质量词后面没有内容了：进后缀。
    expect(zoneOf("best quality")).toBe("suffix");
    const state = applySuggestions(splitStateOf(base), suggestions);
    expect(texts(commitSplit(base, state).prefix)).toEqual(["artist:foo"]);
  });

  it("classifies tokens like the backend", () => {
    expect(tokenCategory("artist:[[unknown]]", {})).toBe("artist");
    expect(tokenCategory("1.2::silver hair, akipeko::", { "silver hair": "appearance", akipeko: "artist" })).toBe("artist");
    expect(tokenCategory("mystery", {})).toBeNull();
  });

  it("counts frequency per post, not per image", () => {
    const image = (id: string, post: string, prompt: string) =>
      ({ id, prompt, post: { dir_name: post, date: null, post_id: null, title: null } }) as unknown as ImageRecord;
    const frequency = postFrequency([
      image("a", "p1", "shirabi, 1girl"),
      image("b", "p1", "shirabi, 1girl"),
      image("c", "p2", "[[shirabi]], solo"),
      image("d", "p3", "other"),
    ]);
    expect(frequency.get("shirabi")).toBeCloseTo(2 / 3);
    expect(frequency.get("1girl")).toBeCloseTo(1 / 3);
  });
});

describe("edit stage", () => {
  const edited = () => commitSplit(recipe("shirabi, 1girl, sitting, school uniform, best quality"), applyCuts(splitStateOf(recipe("shirabi, 1girl, sitting, school uniform, best quality")), 1, 4));

  it("moves subject tokens into the style prefix", () => {
    const base = edited();
    const uniform = base.subject.find((token) => token.text === "school uniform")!;
    const moved = moveTokens(base, [uniform.id], "prefix");
    expect(texts(moved.prefix)).toEqual(["shirabi", "school uniform"]);
    expect(texts(moved.subject)).toEqual(["1girl", "sitting"]);
    const front = moveTokens(base, [uniform.id], "suffix", "start");
    expect(texts(front.suffix)).toEqual(["school uniform", "best quality"]);
  });

  it("places a dragged token at an index", () => {
    const base = edited();
    const sitting = base.subject.find((token) => token.text === "sitting")!;
    expect(texts(placeToken(base, sitting.id, "subject", 0).subject)).toEqual(["sitting", "1girl", "school uniform"]);
    expect(texts(placeToken(base, sitting.id, "suffix", 1).suffix)).toEqual(["best quality", "sitting"]);
  });

  it("adds card tags without duplicates and removes by origin", () => {
    const base = edited();
    const { recipe: withCard, added } = addTokens(base, ["red eyes", "sitting", "  ", "long hair"], "character:krul");
    expect(added).toBe(2);
    expect(texts(withCard.subject)).toEqual(["1girl", "sitting", "school uniform", "red eyes", "long hair"]);
    expect(withCard.subject.find((token) => token.text === "sitting")!.origins).toEqual(["source", "character:krul"]);
    const removed = removeOrigin(withCard, "character:krul");
    expect(texts(removed.subject)).toEqual(["1girl", "sitting", "school uniform"]);
    expect(removed.subject.find((token) => token.text === "sitting")!.origins).toEqual(["source"]);
  });

  it("does not merge a zero-weighted tag with the plain tag", () => {
    const base = recipe("1girl, 0.0::loli::, {red eyes}");
    const { recipe: next, added } = addTokens(base, ["loli", "red eyes"], "character:x");
    expect(added).toBe(1);
    expect(texts(next.subject)).toEqual(["1girl", "0.0::loli::", "{red eyes}", "loli"]);
    expect(next.subject[2].origins).toEqual(["source", "character:x"]);
  });

  it("keeps ids and origins when the subject is edited as text", () => {
    const base = edited();
    const next = retokenize(base.subject, "1girl, sitting on bed, school uniform");
    expect(next[0].id).toBe(base.subject[0].id);
    expect(next[1].origins).toEqual(["manual"]);
    expect(next[2].id).toBe(base.subject[2].id);
  });

  it("restores the source subject without touching locked style", () => {
    const base = moveTokens(edited(), [], "subject");
    const changed = { ...base, subject: [] };
    const restored = restoreSourceSubject(changed, "shirabi, 1girl, sitting, school uniform, best quality");
    expect(texts(restored.subject)).toEqual(["1girl", "sitting", "school uniform"]);
    expect(texts(restored.prefix)).toEqual(["shirabi"]);
  });
});
