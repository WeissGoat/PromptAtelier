import { describe, expect, it } from "vitest";

import type { ImageRecord, Recipe, RecipeToken } from "./api";
import {
  addTokens,
  commitTextSplit,
  markRange,
  markTokens,
  moveTokens,
  placeToken,
  postFrequency,
  removeOrigin,
  restoreSourceSubject,
  retokenize,
  snapRange,
  suggestTextMarks,
  suggestZones,
  textSplitOf,
  tokenCategory,
  tokensToText,
  type TextSplit,
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
    character: { enabled: false, captions: [], add_male_caption: true },
    negative: [],
    model: null,
    params: {},
    use_source_vibe: false,
    flags: [],
    notes: "",
  };
}

const texts = (list: RecipeToken[]) => list.map((token) => token.text);

/** 按原文里的文字标记（取第一次出现的位置）。 */
function mark(split: TextSplit, piece: string, zone: Parameters<typeof markRange>[3]): TextSplit {
  const start = split.text.indexOf(piece);
  return markRange(split, start, start + piece.length, zone);
}

describe("split stage", () => {
  it("marks prefix and suffix on the text; the rest is subject", () => {
    const base = recipe("shirabi|[[akipeko]], 1girl, sitting, smooth shading, best quality");
    let split = textSplitOf(base, "shirabi|[[akipeko]], 1girl, sitting, smooth shading, best quality");
    expect(split.marks).toEqual([]);
    split = mark(split, "shirabi|[[akipeko]]", "prefix");
    split = mark(split, "smooth shading, best quality", "suffix");
    const committed = commitTextSplit(base, split);
    // 标出的一段整体是一块，里面不再分词；没标的主体照常分词。
    expect(texts(committed.prefix)).toEqual(["shirabi|[[akipeko]]"]);
    expect(texts(committed.subject)).toEqual(["1girl", "sitting"]);
    expect(texts(committed.suffix)).toEqual(["smooth shading, best quality"]);
    expect(committed.stage).toBe("edit");
    expect(committed.locked).toBe(true);
    // 没变的 token 沿用原来的 id。
    expect(committed.subject[0].id).toBe(base.subject[2].id);

    // 按 tag 拆开标：每个 tag 各成一块，原文的竖线分隔符保留，拼回去和原文一致。
    const start = split.text.indexOf("shirabi");
    const perTag = commitTextSplit(base, markTokens(split, start, start + "shirabi|[[akipeko]]".length, "prefix"));
    expect(texts(perTag.prefix)).toEqual(["shirabi", "[[akipeko]]"]);
    expect(tokensToText(perTag.prefix)).toBe("shirabi|[[akipeko]]");
  });

  it("splits by characters where the tokenizer cannot, and finds the pieces again", () => {
    const prompt = "1boy,1girl-1::,Chibi character,Too precise hair::\nmosaic censorship";
    const base = recipe(prompt);
    const split = mark(textSplitOf(base, prompt), "-1::,Chibi character,Too precise hair::", "dropped");
    const committed = commitTextSplit(base, split);
    expect(texts(committed.subject)).toEqual(["1boy", "1girl", "mosaic censorship"]);
    expect(texts(committed.dropped)).toEqual(["-1::,Chibi character,Too precise hair::"]);
    // 重新划分：紧贴在 1girl 后面的那块也能在原文里找回原位。
    const again = textSplitOf(committed, prompt);
    expect(again.text).toBe(prompt);
    expect(again.marks.map((item) => [again.text.slice(item.start, item.end), item.zone])).toEqual([
      ["-1::,Chibi character,Too precise hair::", "dropped"],
    ]);
  });

  it("cuts natural-language sentences where the text was selected", () => {
    const prompt = "color trace, 这是一幅日式动漫插画。采用细腻的线稿，少女站在中央。looking back, very aesthetic, masterpiece";
    const base = recipe(prompt);
    let split = textSplitOf(base, prompt);
    split = mark(split, "color trace, 这是一幅日式动漫插画。采用细腻的线稿", "prefix");
    split = mark(split, "very aesthetic, masterpiece", "suffix");
    const committed = commitTextSplit(base, split);
    expect(texts(committed.prefix)).toEqual(["color trace, 这是一幅日式动漫插画。采用细腻的线稿"]);
    expect(texts(committed.subject)).toEqual(["少女站在中央。looking back"]);
    expect(texts(committed.suffix)).toEqual(["very aesthetic, masterpiece"]);
  });

  it("takes a drag by characters, only trimming spaces and commas at the ends", () => {
    const group = "1.1::year 2025, year 2026,::";
    const text = `color trace, ${group}, smile`;
    expect(snapRange(text, 2, 13)).toEqual([2, 11]);
    const inside = text.indexOf("2025");
    expect(snapRange(text, inside, inside + 4)).toEqual([inside, inside + 4]);
    expect(snapRange(text, 11, 13)).toBeNull();
  });

  it("re-marks and clears marks; each mark stays its own block", () => {
    let split: TextSplit = { text: "a, b, c, d", marks: [] };
    split = mark(split, "a", "prefix");
    split = mark(split, "b", "prefix");
    expect(split.marks).toEqual([
      { start: 0, end: 1, zone: "prefix" },
      { start: 3, end: 4, zone: "prefix" },
    ]);
    split = mark(split, "b", "subject");
    expect(split.marks).toEqual([{ start: 0, end: 1, zone: "prefix" }]);
    split = mark(split, "c, d", "suffix");
    split = mark(split, "d", "dropped");
    expect(split.marks).toEqual([
      { start: 0, end: 1, zone: "prefix" },
      { start: 6, end: 7, zone: "suffix" },
      { start: 9, end: 10, zone: "dropped" },
    ]);
  });

  it("re-splits an edited recipe without losing style tokens or added materials", () => {
    const prompt = "shirabi, 1girl, sitting, best quality";
    const first = commitTextSplit(recipe(prompt), mark(mark(textSplitOf(recipe(prompt), prompt), "shirabi", "prefix"), "best quality", "suffix"));
    const edited = {
      ...addTokens(first, ["miku"], "character:F:/miku").recipe,
      prefix: [...first.prefix, { id: "m1", text: "ink wash", sep: ", ", origins: ["manual"] }],
    };
    const split = textSplitOf(edited, prompt);
    // 原文里找到的标回原位，手打的接在末尾。
    expect(split.text).toBe("shirabi, 1girl, sitting, best quality, ink wash");
    expect(split.marks.map((item) => [split.text.slice(item.start, item.end), item.zone])).toEqual([
      ["shirabi", "prefix"],
      ["best quality", "suffix"],
      ["ink wash", "prefix"],
    ]);
    // 之前从主体里删掉的原文标成丢弃，不会悄悄回到主体。
    const trimmed = { ...edited, subject: edited.subject.filter((token) => token.text !== "sitting") };
    const resplit = textSplitOf(trimmed, prompt);
    expect(resplit.marks.map((item) => [resplit.text.slice(item.start, item.end), item.zone])).toContainEqual(["sitting", "dropped"]);
    expect(texts(commitTextSplit(trimmed, resplit).subject)).toEqual(["1girl", "miku"]);

    const again = commitTextSplit(edited, mark(split, "best quality", "subject"));
    expect(texts(again.prefix)).toEqual(["shirabi", "ink wash"]);
    expect(texts(again.subject)).toEqual(["1girl", "sitting", "best quality", "miku"]);
    expect(again.subject[3].origins).toEqual(["character:F:/miku"]);
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
    const prompt = tokensToText(base.subject);
    const adopted = suggestTextMarks(textSplitOf(base, prompt), categories, frequency);
    expect(adopted.unsure).toBe(3);
    expect(texts(commitTextSplit(base, adopted.split).prefix)).toEqual(["artist:foo"]);
    expect(texts(commitTextSplit(base, adopted.split).suffix)).toEqual(["best quality"]);
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
  const edited = () => {
    const prompt = "shirabi, 1girl, sitting, school uniform, best quality";
    const split = mark(mark(textSplitOf(recipe(prompt), prompt), "shirabi", "prefix"), "best quality", "suffix");
    return commitTextSplit(recipe(prompt), split);
  };

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
