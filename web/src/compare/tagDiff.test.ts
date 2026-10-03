import { describe, expect, it } from "vitest";

import { applyTagDiff, computeTagDiff, normalizeTag, tokenizePrompt } from "./tagDiff";

describe("tagDiff engine", () => {
  it("tokenizes prompts splitting by commas, full-width commas, and newlines", () => {
    const raw = "1girl, solo,  school uniform ， black ribbon\ncinematic lighting,";
    const tokens = tokenizePrompt(raw);
    expect(tokens).toEqual([
      "1girl",
      "solo",
      "school uniform",
      "black ribbon",
      "cinematic lighting",
    ]);
  });

  it("normalizes tags for case, extra whitespace, and underscores", () => {
    expect(normalizeTag("School_Uniform")).toBe("school uniform");
    expect(normalizeTag("  1GIRL  ")).toBe("1girl");
    expect(normalizeTag("{Detailed_Eyes}")).toBe("{detailed eyes}");
  });

  it("computes added and removed tags accurately", () => {
    const base = "1girl, solo, school uniform, black hair, smiling";
    const variant = "1girl, solo, school uniform, black hair, crying, film grain";

    const diff = computeTagDiff(base, variant);

    expect(diff.added).toEqual(["crying", "film grain"]);
    expect(diff.removed).toEqual(["smiling"]);
    expect(diff.tokens).toEqual([
      { text: "1girl", type: "unchanged" },
      { text: "solo", type: "unchanged" },
      { text: "school uniform", type: "unchanged" },
      { text: "black hair", type: "unchanged" },
      { text: "crying", type: "added" },
      { text: "film grain", type: "added" },
    ]);
  });

  it("handles identical prompts as unchanged", () => {
    const base = "masterpiece, 1girl, best quality";
    const variant = "masterpiece, 1girl, best quality";

    const diff = computeTagDiff(base, variant);
    expect(diff.added).toEqual([]);
    expect(diff.removed).toEqual([]);
    expect(diff.tokens.every((t) => t.type === "unchanged")).toBe(true);
  });

  it("preserves brackets and weights in tokens while comparing canonical forms", () => {
    const base = "1girl, (masterpiece:1.2)";
    const variant = "1girl, (masterpiece:1.2), {photorealistic}";

    const diff = computeTagDiff(base, variant);
    expect(diff.added).toEqual(["{photorealistic}"]);
    expect(diff.removed).toEqual([]);
  });

  it("applies tag diff onto a new base prompt adding and removing tokens", () => {
    const base = "1girl, solo, black hair, looking at viewer";
    const diff = {
      added: ["smiling", "red dress"],
      removed: ["black hair"],
    };

    const result = applyTagDiff(base, diff);
    expect(result).toBe("1girl, solo, looking at viewer, smiling, red dress");
  });

  it("applies empty diff without changing prompt", () => {
    const base = "1girl, solo, masterpiece";
    expect(applyTagDiff(base, { added: [], removed: [] })).toBe("1girl, solo, masterpiece");
    expect(applyTagDiff(base, undefined)).toBe("1girl, solo, masterpiece");
  });

  it("detects deleted duplicate tags in computeTagDiff", () => {
    const base = "1girl, solo, smile, smile";
    const variant = "1girl, solo, smile";

    const diff = computeTagDiff(base, variant);
    expect(diff.removed).toEqual(["smile"]);
    expect(diff.added).toEqual([]);
    expect(diff.tokens).toEqual([
      { text: "1girl", type: "unchanged" },
      { text: "solo", type: "unchanged" },
      { text: "smile", type: "unchanged" },
    ]);
  });

  it("detects multiple deleted duplicate tags in computeTagDiff", () => {
    const base = "very aesthetic, 1girl, solo, very aesthetic, masterpiece, very aesthetic";
    const variant = "1girl, solo, very aesthetic, masterpiece";

    const diff = computeTagDiff(base, variant);
    expect(diff.removed).toEqual(["very aesthetic", "very aesthetic"]);
    expect(diff.added).toEqual([]);
  });

  it("detects added duplicate tags in computeTagDiff", () => {
    const base = "1girl, solo, smile";
    const variant = "1girl, solo, smile, smile";

    const diff = computeTagDiff(base, variant);
    expect(diff.added).toEqual(["smile"]);
    expect(diff.removed).toEqual([]);
    expect(diff.tokens).toEqual([
      { text: "1girl", type: "unchanged" },
      { text: "solo", type: "unchanged" },
      { text: "smile", type: "unchanged" },
      { text: "smile", type: "added" },
    ]);
  });

  it("applies duplicate removal correctly in applyTagDiff", () => {
    const base = "1girl, solo, smile, smile";
    const diff = { removed: ["smile"] };
    const result = applyTagDiff(base, diff);
    expect(result).toBe("1girl, solo, smile");
  });
});
