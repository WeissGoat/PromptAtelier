import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Recipe, RecipeToken } from "./api";
import { RecipeEditor } from "./RecipeEditor";

function block(id: string, text: string): RecipeToken {
  return { id, text, sep: "", origins: ["source"] };
}

function draft(): Recipe {
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
    prefix: [block("p", "artist:foo, flat color")],
    subject: [block("s", "1girl, sitting")],
    suffix: [],
    dropped: [],
    character: { enabled: true, captions: [{ tokens: [block("c", "girl, akemi homura")], negative: [] }], add_male_caption: false },
    negative: [],
    model: null,
    params: {},
    use_source_vibe: false,
    flags: [],
    notes: "",
  };
}

function renderEditor(onChange = vi.fn()) {
  render(
    <RecipeEditor
      analysisReady
      categories={{}}
      draft={draft()}
      frequency={new Map()}
      onChange={onChange}
      preview={null}
      previewError={null}
      source={null}
      translateOn={false}
    />,
  );
  return onChange;
}

afterEach(cleanup);

describe("recipe blocks", () => {
  it("edits a block in place on double click; locked style blocks stay read-only", () => {
    const onChange = renderEditor();
    fireEvent.doubleClick(screen.getByText("1girl, sitting"));
    const box = screen.getByRole("textbox", { name: "编辑主体的一块" });
    fireEvent.change(box, { target: { value: "1girl-1::,chibi::, smile" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect((onChange.mock.calls[0][0] as Recipe).subject.map((token) => token.text)).toEqual(["1girl-1::,chibi::, smile"]);

    // 锁定的前缀双击不进编辑。
    fireEvent.doubleClick(screen.getByText("artist:foo, flat color"));
    expect(screen.queryByRole("textbox", { name: "编辑画风前缀的一块" })).toBeNull();

    // Esc 取消，不提交。
    fireEvent.doubleClick(screen.getByText("1girl, sitting"));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "编辑主体的一块" }), { key: "Escape" });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("deletes a block with its × button; locked style blocks have none", () => {
    const onChange = renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "删除 1girl, sitting" }));
    expect((onChange.mock.calls[0][0] as Recipe).subject).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "删除 girl, akemi homura" }));
    expect((onChange.mock.calls[1][0] as Recipe).character.captions[0].tokens).toEqual([]);
    expect(screen.queryByRole("button", { name: "删除 artist:foo, flat color" })).toBeNull();
  });

  it("uses the same blocks in character captions", () => {
    const onChange = renderEditor();
    fireEvent.doubleClick(screen.getByText("girl, akemi homura"));
    const box = screen.getByRole("textbox", { name: "编辑角色提示词 #1的一块" });
    fireEvent.change(box, { target: { value: "girl, hatsune miku" } });
    fireEvent.blur(box);
    const next = onChange.mock.calls[0][0] as Recipe;
    expect(next.character.captions[0].tokens.map((token) => token.text)).toEqual(["girl, hatsune miku"]);

    fireEvent.click(screen.getByRole("button", { name: "角色提示词 #1 加一块" }));
    const added = screen.getByRole("textbox", { name: "角色提示词 #1新加的一块" });
    fireEvent.change(added, { target: { value: "sitting, looking back" } });
    fireEvent.keyDown(added, { key: "Enter" });
    const withBlock = onChange.mock.calls[1][0] as Recipe;
    expect(withBlock.character.captions[0].tokens.map((token) => token.text)).toEqual(["girl, akemi homura", "sitting, looking back"]);
  });

  it("drags a subject block into a character caption", () => {
    const onChange = renderEditor();
    const data = new Map<string, string>();
    const dataTransfer = {
      types: ["text/x-token-id"],
      setData: (type: string, value: string) => data.set(type, value),
      getData: (type: string) => data.get(type) ?? "",
      effectAllowed: "move",
    };
    fireEvent.dragStart(screen.getByText("1girl, sitting"), { dataTransfer });
    const target = screen.getByText("girl, akemi homura");
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });
    const next = onChange.mock.calls[0][0] as Recipe;
    expect(next.subject).toEqual([]);
    expect(next.character.captions[0].tokens.map((token) => token.text)).toEqual(["1girl, sitting", "girl, akemi homura"]);
  });

  it("adds a block and splits a selected block by tag", () => {
    const onChange = renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "主体加一块" }));
    const added = screen.getByRole("textbox", { name: "主体新加的一块" });
    fireEvent.change(added, { target: { value: "smile, blush" } });
    fireEvent.keyDown(added, { key: "Enter" });
    expect((onChange.mock.calls[0][0] as Recipe).subject.map((token) => token.text)).toEqual(["1girl, sitting", "smile, blush"]);

    fireEvent.click(screen.getByText("1girl, sitting"));
    expect(screen.getByRole("button", { name: /合并成一块/ })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: /按 tag 拆开/ }));
    expect((onChange.mock.calls[1][0] as Recipe).subject.map((token) => token.text)).toEqual(["1girl", "sitting"]);
  });
});
