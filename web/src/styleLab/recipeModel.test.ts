import { describe, expect, it } from "vitest";

import type { ImageRecord, Recipe, RecipeToken } from "./api";
import {
  addBlock,
  addTokens,
  canSplit,
  commitTextSplit,
  editToken,
  markRange,
  markTokens,
  mergeTokens,
  moveBlock,
  moveTokens,
  placeToken,
  postFrequency,
  removeOrigin,
  restoreSourceSubject,
  retokenize,
  snapRange,
  splitToken,
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
    // 每段整体是一块，里面不分词：标出的是一块，两段标记之间没标的主体也是一块。
    expect(texts(committed.prefix)).toEqual(["shirabi|[[akipeko]]"]);
    expect(texts(committed.subject)).toEqual(["1girl, sitting"]);
    expect(texts(committed.suffix)).toEqual(["smooth shading, best quality"]);
    expect(committed.stage).toBe("edit");
    expect(committed.locked).toBe(true);
    // 再锁定一次，没变的块沿用原来的 id。
    expect(commitTextSplit(committed, textSplitOf(committed, split.text)).subject[0].id).toBe(committed.subject[0].id);

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
    expect(texts(committed.subject)).toEqual(["1boy,1girl", "mosaic censorship"]);
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
    // 主体那块改成只剩 1girl：删掉的原文标成丢弃，不会悄悄回到主体。
    const trimmed = editToken(edited, edited.subject[0].id, "1girl");
    const resplit = textSplitOf(trimmed, prompt);
    expect(resplit.marks.map((item) => [resplit.text.slice(item.start, item.end), item.zone])).toContainEqual(["sitting", "dropped"]);
    expect(texts(commitTextSplit(trimmed, resplit).subject)).toEqual(["1girl", "miku"]);

    const again = commitTextSplit(edited, mark(split, "best quality", "subject"));
    expect(texts(again.prefix)).toEqual(["shirabi", "ink wash"]);
    expect(texts(again.subject)).toEqual(["1girl, sitting, best quality", "miku"]);
    expect(again.subject[1].origins).toEqual(["character:F:/miku"]);
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

  it("adopts suggestions as whole runs, or per tag on request", () => {
    const prompt = "artist:a, artist:b, 1girl, best quality, very aesthetic";
    const base = recipe(prompt);
    const categories = { "1girl": "count", "best quality": "quality", "very aesthetic": "quality" } as const;
    const frequency = new Map([["best quality", 1], ["very aesthetic", 1]]);
    const runs = commitTextSplit(base, suggestTextMarks(textSplitOf(base, prompt), categories, frequency).split);
    expect(texts(runs.prefix)).toEqual(["artist:a, artist:b"]);
    expect(texts(runs.suffix)).toEqual(["best quality, very aesthetic"]);
    const perTag = commitTextSplit(base, suggestTextMarks(textSplitOf(base, prompt), categories, frequency, true).split);
    expect(texts(perTag.prefix)).toEqual(["artist:a", "artist:b"]);
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

  // 主体按 tag 拆开后的配方：1girl / sitting / school uniform 各一块。
  const perTag = () => {
    const base = edited();
    return splitToken(base, base.subject[0].id);
  };

  it("keeps the unmarked subject as one block", () => {
    expect(texts(edited().subject)).toEqual(["1girl, sitting, school uniform"]);
  });

  it("moves subject tokens into the style prefix", () => {
    const base = perTag();
    const uniform = base.subject.find((token) => token.text === "school uniform")!;
    const moved = moveTokens(base, [uniform.id], "prefix");
    expect(texts(moved.prefix)).toEqual(["shirabi", "school uniform"]);
    expect(texts(moved.subject)).toEqual(["1girl", "sitting"]);
    const front = moveTokens(base, [uniform.id], "suffix", "start");
    expect(texts(front.suffix)).toEqual(["school uniform", "best quality"]);
  });

  it("places a dragged token at an index", () => {
    const base = perTag();
    const sitting = base.subject.find((token) => token.text === "sitting")!;
    expect(texts(placeToken(base, sitting.id, "subject", 0).subject)).toEqual(["sitting", "1girl", "school uniform"]);
    expect(texts(placeToken(base, sitting.id, "suffix", 1).suffix)).toEqual(["best quality", "sitting"]);
  });

  it("adds a card as one block and removes it by origin", () => {
    const base = edited();
    const { recipe: withCard, added } = addTokens(base, ["red eyes", "sitting", "  ", "long hair"], "character:krul");
    expect(added).toBe(1);
    expect(texts(withCard.subject)).toEqual(["1girl, sitting, school uniform", "red eyes, sitting, long hair"]);
    const removed = removeOrigin(withCard, "character:krul");
    expect(texts(removed.subject)).toEqual(["1girl, sitting, school uniform"]);
  });

  it("edits, adds, merges and splits blocks without retokenizing anything else", () => {
    const base = edited();
    const block = base.subject[0];
    // 双击改文字：改过的原图块记为手打；清空就删掉。
    const changed = editToken(base, block.id, "1girl-1::,chibi::, sitting");
    expect(texts(changed.subject)).toEqual(["1girl-1::,chibi::, sitting"]);
    expect(changed.subject[0].origins).toEqual(["manual"]);
    expect(editToken(base, block.id, "  ").subject).toEqual([]);
    // 加一块：整段是一块。
    const added = addBlock(base, "subject", "looking back, smile");
    expect(texts(added.subject)).toEqual(["1girl, sitting, school uniform", "looking back, smile"]);
    // 拆开再合并，文字和原来一样。
    const split = splitToken(added, added.subject[1].id);
    expect(texts(split.subject)).toEqual(["1girl, sitting, school uniform", "looking back", "smile"]);
    expect(canSplit(split.subject[1])).toBe(false);
    const merged = mergeTokens(split, [split.subject[1].id, split.subject[2].id]);
    expect(texts(merged.subject)).toEqual(["1girl, sitting, school uniform", "looking back, smile"]);
    // 角色提示词里的块也一样。
    const withCaption = { ...base, character: { ...base.character, captions: [{ tokens: tokens("girl, sitting"), negative: [] }] } };
    const merge = mergeTokens(withCaption, withCaption.character.captions[0].tokens.map((token) => token.id));
    expect(texts(merge.character.captions[0].tokens)).toEqual(["girl, sitting"]);
  });

  it("drags blocks between zones and character captions", () => {
    const base = perTag();
    const sitting = base.subject.find((token) => token.text === "sitting")!;
    // 主体里的动作拖进第 1 条角色提示词（还没有就新加一条，并开启角色提示词）。
    const moved = moveBlock(base, sitting.id, { caption: 0 });
    expect(texts(moved.subject)).toEqual(["1girl", "school uniform"]);
    expect(texts(moved.character.captions[0].tokens)).toEqual(["sitting"]);
    expect(moved.character.enabled).toBe(true);
    // 放到已有块的前面；再拖回主体指定位置。
    const uniform = base.subject.find((token) => token.text === "school uniform")!;
    const front = moveBlock(moved, uniform.id, { caption: 0 }, 0);
    expect(texts(front.character.captions[0].tokens)).toEqual(["school uniform", "sitting"]);
    const back = moveBlock(front, sitting.id, "subject", 0);
    expect(texts(back.subject)).toEqual(["sitting", "1girl"]);
    expect(texts(back.character.captions[0].tokens)).toEqual(["school uniform"]);
    // 按键挪动也能把角色提示词里的块挪回区里。
    const keyed = moveTokens(front, [uniform.id], "suffix");
    expect(texts(keyed.suffix)).toEqual(["best quality", "school uniform"]);
    expect(texts(keyed.character.captions[0].tokens)).toEqual(["sitting"]);
  });

  it("keeps ids and origins when a negative prompt is edited as text", () => {
    const base = tokens("1girl, sitting, school uniform");
    const next = retokenize(base, "1girl, sitting on bed, school uniform");
    expect(next[0].id).toBe(base[0].id);
    expect(next[1].origins).toEqual(["manual"]);
    expect(next[2].id).toBe(base[2].id);
  });

  it("restores the source subject without touching locked style", () => {
    const base = moveTokens(edited(), [], "subject");
    const changed = { ...base, subject: [] };
    const restored = restoreSourceSubject(changed, "shirabi, 1girl, sitting, school uniform, best quality");
    expect(texts(restored.subject)).toEqual(["1girl, sitting, school uniform"]);
    expect(texts(restored.prefix)).toEqual(["shirabi"]);
  });
});
