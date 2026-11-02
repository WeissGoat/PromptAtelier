import { describe, expect, it } from "vitest";

import { buildOriginIndex, diffAgainstSource, markPrompt, segmentText, tokenizePrompt } from "./analysis";
import type { ContractFrame, ContractSources } from "./types";

const sources: ContractSources = {
  characters: {
    c1: {
      ref: "series/homura",
      path: "/d/角色/series/homura",
      id: "homura",
      name: "homura",
      sections: { character: ["akemi_homura"], hair: ["black_hair", "long_hair"] },
      negative: [],
      content_hash: "x",
    },
  },
  action_group: {
    ref: "stn_1",
    name: "stn_1",
    path: "/d/动作改2/stn_1",
    kind: "stn",
    member_count: 1,
    content_hash: "y",
    members: [
      {
        index: 1,
        name: "01_站立",
        title: "站立",
        ref: "new/a",
        group_ref: "stn_1/01_站立",
        path: "/d/动作改2/stn_1/01_站立",
        positive: "1girl, solo, leaning forward, white background, long hair",
        negative: "",
        source_file: "meta.yaml",
        classify: {},
        character_scope: null,
        clothing_state: null,
      },
    ],
  },
  clothing: null,
  background: null,
  references: {},
};

const frame: ContractFrame = {
  id: "f01",
  title: "站立",
  source: "new/a",
  is_custom: false,
  inspired_by: [],
  characters: ["c1"],
  size: null,
  meta: {},
  notes: "",
  prompts: {},
  submit: {},
  member_ref: "new/a",
  member_index: 1,
  prompt_hash: "h",
};

describe("tokenizePrompt", () => {
  it("strips weights and keeps positions", () => {
    const text = "1.2::leaning forward, bent over::,\n{smile}, (night:1.3), black hair";
    const tags = tokenizePrompt(text);
    expect(tags.map((tag) => tag.key)).toEqual(["leaning_forward", "bent_over", "smile", "night", "black_hair"]);
    expect(tags.map((tag) => tag.weight)).toEqual([1.2, 1.2, 1.05, 1.3, 1]);
    expect(text.slice(tags[2].start, tags[2].end)).toBe("{smile}");
    expect(tags[2].line).toBe(1);
  });
});

describe("markPrompt", () => {
  it("marks origins, additions, rewrites and multi-source tags", () => {
    const index = buildOriginIndex(frame, sources);
    const marked = markPrompt("akemi_homura, black hair, long_hair, 1girl, 1.2::leaning forward::, classroom", index);
    const byKey = Object.fromEntries(marked.map((tag) => [tag.key, tag]));
    expect(byKey.akemi_homura.origins[0]).toMatchObject({ kind: "character", id: "c1", section: "character" });
    expect(byKey.akemi_homura.rewritten).toBe(false);
    expect(byKey.black_hair.rewritten).toBe(true);
    expect(byKey.long_hair.origins.map((origin) => origin.kind).sort()).toEqual(["action", "character"]);
    expect(byKey.leaning_forward.rewritten).toBe(true);
    expect(byKey.classroom.added).toBe(true);
  });

  it("segments keep separators and newlines", () => {
    const text = "a,\n b";
    const segments = segmentText(text, markPrompt(text, new Map()));
    expect(segments.map((segment) => segment.text).join("")).toBe(text);
    expect(segments.filter((segment) => segment.tag).length).toBe(2);
  });
});

describe("diffAgainstSource", () => {
  it("lists only rewrites, removals and additions", () => {
    const diff = diffAgainstSource("1girl, {solo}, leaning forward, classroom", "1girl, solo, leaning forward, white background");
    expect(diff).toEqual([
      expect.objectContaining({ type: "rewrite", key: "solo", from: "solo", to: "{solo}" }),
      expect.objectContaining({ type: "added", key: "classroom" }),
      expect.objectContaining({ type: "removed", key: "white_background" }),
    ]);
  });
});
