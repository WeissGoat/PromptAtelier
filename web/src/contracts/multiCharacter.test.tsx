import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { blockCharacters, buildOriginIndex, diffAgainstSource, flattenInlineCharacters, markPrompt, orderBlockKeys } from "./analysis";
import { buildFrameRequest, DEFAULT_GENERATE_SETTINGS, type GenerateSettings } from "./ContractGeneratePanel";
import { FrameCard } from "./FrameCard";
import type { ContractDetail, ContractFrame, ContractSources, SourceNode } from "./types";

function character(id: string, sections: Record<string, string[]>): SourceNode {
  return {
    ref: `series/${id}`,
    path: `/d/角色/series/${id}`,
    id,
    name: id,
    character_id: id,
    sections: { copyright: ["madoka_magica"], ...sections },
    negative: [],
    content_hash: "x",
  };
}

const ACTION_POSITIVE =
  "2girls, yuri, sitting on lap, ::character A: girl, someone_a, sitting behind, 1.2::smile:: ::, ::character B: girl, someone_b, open mouth ::";

const sources: ContractSources = {
  characters: {
    c1: character("akemi_homura", { character: ["akemi_homura"], hair: ["black_hair"] }),
    c2: character("kaname_madoka", { character: ["kaname_madoka"], hair: ["pink_hair"] }),
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
        name: "01_坐",
        title: "坐",
        ref: "stn_1/01_坐",
        group_ref: "stn_1/01_坐",
        path: "/d/动作改2/stn_1/01_坐",
        positive: ACTION_POSITIVE,
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

const prompts = {
  "positive c2": "girl, kaname_madoka, pink_hair, open mouth, black_hair",
  negative: "simple background",
  positive: "2girls, yuri, sitting on lap,\nmadoka_magica",
  "positive c1": "girl, akemi_homura, black_hair, sitting behind, 1.2::smile::",
  "negative c1": "red_glasses",
};

const frame: ContractFrame = {
  id: "f01",
  title: "坐",
  source: "stn_1/01_坐",
  is_custom: false,
  inspired_by: [],
  characters: ["c1", "c2"],
  size: null,
  meta: {},
  notes: "",
  prompts,
  submit: { ...prompts, positive: "2girls, yuri, sitting on lap, madoka_magica" },
  character_prompts: [
    { id: "c1", positive: prompts["positive c1"], negative: "red_glasses" },
    { id: "c2", positive: prompts["positive c2"], negative: "" },
  ],
  member_ref: "stn_1/01_坐",
  member_index: 1,
  prompt_hash: "h",
  token_usage: null,
};

const detail = { id: "demo", request: { title: "" }, sources } as unknown as ContractDetail;
const settings: GenerateSettings = { ...DEFAULT_GENERATE_SETTINGS, artist: { ref: "artist/a", name: "a" } as never, negative: "lowres" };

describe("multi-character blocks", () => {
  it("orders blocks main → c1 → c2, positive before negative", () => {
    expect(orderBlockKeys(Object.keys(prompts), ["c1", "c2"])).toEqual([
      "positive",
      "negative",
      "positive c1",
      "negative c1",
      "positive c2",
    ]);
    expect(blockCharacters(prompts, ["c1", "c2"])).toEqual(["c1", "c2"]);
  });

  it("flattens inline ::character X: blocks without touching numeric weights", () => {
    const flat = flattenInlineCharacters(ACTION_POSITIVE);
    expect(flat).not.toContain("::character");
    const expected = "2girls, yuri, sitting on lap, girl, someone_a, sitting behind, 1.2::smile::, girl, someone_b, open mouth";
    expect(diffAgainstSource(flat, expected)).toEqual([]);
    expect(flattenInlineCharacters("a, 1.2::smile::, b")).toBe("a, 1.2::smile::, b");
  });

  it("marks another character's words written in the wrong block", () => {
    const index = buildOriginIndex(frame, sources, "positive");
    const c2 = markPrompt(prompts["positive c2"], index, { character: "c2", splitCharacters: ["c1", "c2"] });
    expect(c2.find((tag) => tag.key === "black_hair")?.misplaced).toBe("c1");
    expect(c2.find((tag) => tag.key === "pink_hair")?.misplaced).toBeUndefined();
    const main = markPrompt("2girls, pink_hair, madoka_magica", index, { character: null, splitCharacters: ["c1", "c2"] });
    expect(main.find((tag) => tag.key === "pink_hair")?.misplaced).toBe("c2");
    // 作品名是两个角色共用的分区，不算写错块。
    expect(main.find((tag) => tag.key === "madoka_magica")?.misplaced).toBeUndefined();
  });

  it("submits character blocks as explicit NovelAI character prompts", () => {
    const item = buildFrameRequest(detail, frame, settings, { backend: "novelai", presets: {} }, "out");
    const request = item.compose_request as unknown as {
      compose: { agent_result: { positive: string; negative: string } };
      render: { params: { character_prompts: Record<string, unknown> } };
    };
    expect(request.compose.agent_result).toEqual({
      positive: "2girls, yuri, sitting on lap, madoka_magica",
      negative: "simple background, lowres",
    });
    expect(request.render.params.character_prompts).toEqual({
      mode: "explicit",
      captions: [
        { positive: prompts["positive c1"], negative: "red_glasses" },
        { positive: prompts["positive c2"], negative: "" },
      ],
      add_male_caption: false,
      unsupported: "merge",
    });
  });

  it("merges character blocks into the main prompt when character prompts are not used", () => {
    for (const [backend, characterPrompts] of [["comfyui", "auto"], ["novelai", "off"]] as const) {
      const item = buildFrameRequest(detail, frame, { ...settings, characterPrompts }, { backend, presets: {} }, "out");
      const request = item.compose_request as unknown as {
        compose: { agent_result: { positive: string; negative: string } };
        render: { params: Record<string, unknown> };
      };
      expect(request.compose.agent_result.positive).toBe(
        `2girls, yuri, sitting on lap, madoka_magica, ${prompts["positive c1"]}, ${prompts["positive c2"]}`,
      );
      expect(request.compose.agent_result.negative).toBe("simple background, red_glasses, lowres");
      expect(request.render.params.character_prompts).toBeUndefined();
    }
  });

  it("keeps auto mode for frames without character blocks", () => {
    const single = { ...frame, prompts: { positive: "1girl" }, submit: { positive: "1girl" }, character_prompts: [] };
    const item = buildFrameRequest(detail, single, settings, { backend: "novelai", presets: {} }, "out");
    const request = item.compose_request as unknown as { render: { params: { character_prompts: Record<string, unknown> } } };
    expect(request.render.params.character_prompts).toEqual({ mode: "auto", add_male_caption: false });
  });

  it("shows character blocks with names and lets the editor add a missing block", () => {
    const noop = () => undefined;
    const props = {
      sources,
      issues: [],
      view: "marked" as const,
      showDiff: true,
      translate: false,
      selected: false,
      results: [],
      saving: false,
      onToggleSelect: noop,
      onGenerate: noop,
      onSave: async () => true,
      onOpenImage: noop,
      onTogglePick: noop,
      onViewAll: noop,
    };
    const { container, unmount } = render(<FrameCard frame={frame} {...props} />);
    const labels = [...container.querySelectorAll(".ct-blocks .ct-block-label")].map((node) => node.textContent);
    expect(labels).toEqual([
      "主提示词 · 正向",
      "主提示词 · 负面",
      "c1 · akemi_homura · 正向",
      "c1 · akemi_homura · 负面",
      "c2 · kaname_madoka · 正向",
    ]);
    expect(container.querySelector(".ct-block-char.origin-c2 .is-misplaced")?.textContent).toContain("black_hair");
    // 词挪进角色块后，Diff 不把它们算作删除。
    expect(within(container.querySelector(".ct-diff") as HTMLElement).queryByText("sitting behind")).toBeNull();
    unmount();

    const onlyMain = { ...frame, prompts: { positive: "2girls" }, submit: { positive: "2girls" }, character_prompts: [] };
    render(<FrameCard frame={onlyMain} {...props} />);
    fireEvent.click(screen.getByText("编辑"));
    fireEvent.click(screen.getByText("+ 添加 c2 · kaname_madoka 角色块"));
    expect(screen.getByText("c2 · kaname_madoka · 正向")).toBeTruthy();
    expect(screen.getByText("+ 添加 c1 · akemi_homura 角色块")).toBeTruthy();
  });
});
