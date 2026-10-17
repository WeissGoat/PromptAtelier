import { afterEach, describe, expect, it } from "vitest";

import {
  defaultPieces,
  isDefaultGrouping,
  loadPieces,
  mergePieces,
  newPiece,
  pieceLabel,
  pieceValid,
  piecesToUnits,
  savePieces,
  splitPiece,
  styleSignature,
} from "./ablationPieces";
import type { Recipe, RecipeToken } from "./api";
import { dropStyleTags, tokensToText } from "./recipeModel";

function block(text: string, id = `b-${text}`): RecipeToken {
  return { id, text, sep: "", origins: ["source"] };
}

function recipe(overrides: Partial<Recipe> = {}): Recipe {
  return {
    schema: "tags-machine-core.style-lab.recipe/v1",
    id: "r-pieces",
    name: "r",
    version: 1,
    created_at: 0,
    updated_at: 0,
    source_image_id: null,
    group_id: null,
    stage: "edit",
    locked: true,
    prefix: [block("artist:foo, 0.6::ixy::, flat color")],
    subject: [block("1girl")],
    suffix: [block("very aesthetic, masterpiece")],
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

afterEach(() => localStorage.clear());

describe("ablation pieces", () => {
  it("splits blocks per tag or keeps whole blocks", () => {
    const draft = recipe();
    expect(defaultPieces(draft, "tag").map(pieceLabel)).toEqual(["artist:foo", "0.6::ixy::", "flat color", "very aesthetic", "masterpiece"]);
    expect(defaultPieces(draft, "block").map(pieceLabel)).toEqual(["artist:foo, 0.6::ixy::, flat color", "very aesthetic, masterpiece"]);
  });

  it("merges, splits and adds pieces, then turns them into units", () => {
    const draft = recipe();
    const pieces = defaultPieces(draft, "tag");
    const merged = mergePieces(pieces, [pieces[1].id, pieces[3].id]);
    expect(merged.pieces.map(pieceLabel)).toEqual(["artist:foo", "0.6::ixy::, very aesthetic", "flat color", "masterpiece"]);
    const back = splitPiece(merged.pieces, merged.merged!);
    expect(back.map(pieceLabel)).toEqual(["artist:foo", "0.6::ixy::", "very aesthetic", "flat color", "masterpiece"]);

    const added = newPiece("masterpiece,  thick lines", draft)!;
    expect([added.remove, added.add]).toEqual([["masterpiece"], ["thick lines"]]);
    const all = [...merged.pieces, added];
    expect(piecesToUnits(all, [merged.merged!, added.id], false)).toEqual([
      { label: "0.6::ixy::, very aesthetic", token_ids: [], remove: ["0.6::ixy::", "very aesthetic"], add: [] },
      { label: "masterpiece, + thick lines", token_ids: [], remove: ["masterpiece"], add: ["thick lines"] },
    ]);
    expect(piecesToUnits(all, [merged.merged!, added.id], true)).toHaveLength(1);

    expect(isDefaultGrouping(pieces, draft, "tag")).toBe(true);
    expect(isDefaultGrouping(defaultPieces(draft, "tag"), draft, "tag")).toBe(true);
    expect(isDefaultGrouping(merged.pieces, draft, "tag")).toBe(false);
    expect(isDefaultGrouping(pieces, draft, "block")).toBe(false);
  });

  it("remembers the grouping per recipe and regroups when the style changes", () => {
    const draft = recipe();
    const pieces = defaultPieces(draft, "block");
    const extra = newPiece("thick lines", draft)!;
    savePieces(draft, "block", [...pieces, extra]);
    expect(loadPieces(draft).pieces).toHaveLength(3);

    const edited = recipe({ suffix: [block("masterpiece")] });
    const reloaded = loadPieces(edited);
    expect(reloaded.mode).toBe("block");
    expect(reloaded.pieces.map(pieceLabel)).toEqual(["artist:foo, 0.6::ixy::, flat color", "masterpiece", "+ thick lines"]);
    expect(pieceValid(pieces[1], edited)).toBe(false);

    // 旧版本存的分组（分词规则变过）也按默认重新分。
    const stale = recipe();
    localStorage.setItem(
      "promptatelier.style-lab.ablation.r-pieces",
      JSON.stringify({ signature: styleSignature(stale), mode: "tag", pieces: [{ id: "old", zone: "prefix", remove: ["::"], add: [] }] }),
    );
    expect(loadPieces(stale).pieces.map(pieceLabel)).toEqual(defaultPieces(stale, "tag").map(pieceLabel));
  });

  it("drops chosen tags out of a whole block into the dropped zone", () => {
    const draft = recipe();
    const next = dropStyleTags(draft, ["0.6::ixy::", "masterpiece"]);
    expect(tokensToText(next.prefix)).toBe("artist:foo, flat color");
    expect(tokensToText(next.suffix)).toBe("very aesthetic");
    expect(next.dropped.map((token) => token.text)).toEqual(["0.6::ixy::", "masterpiece"]);
    expect(dropStyleTags(draft, ["not there"])).toBe(draft);
  });
});
