import { describe, expect, it } from "vitest";

import { computeTagDiff, normalizeTag, tokenizePrompt } from "./tagDiff";

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
});
