import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Recipe, WorkspacePayload } from "./api";
import { CustomWorkspaceProvider } from "../workspace/CustomWorkspaceProvider";

const api = vi.hoisted(() => ({
  listWorkspaces: vi.fn(),
  getLLMStatus: vi.fn(),
  createImageGroup: vi.fn(),
  uploadImages: vi.fn(),
  getRecipe: vi.fn(),
  saveNewRecipe: vi.fn(),
  saveRecipe: vi.fn(),
  previewRecipe: vi.fn(),
  listRecipeRuns: vi.fn(),
  getExportDefaults: vi.fn(),
  getShelf: vi.fn(),
  saveShelf: vi.fn(),
  searchMaterials: vi.fn(),
}));

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return { ...actual, ...api };
});

import { resetShelfForTests } from "./materialShelf";
import { RecipeWorkspace } from "./RecipeWorkspace";
import { StyleLabPage } from "./StyleLabPage";

function draftRecipe(): Recipe {
  return {
    schema: "tags-machine-core.style-lab.recipe/v1",
    id: "new1",
    name: "配方 · a",
    version: 0,
    created_at: 0,
    updated_at: 0,
    source_image_id: null,
    group_id: null,
    stage: "split",
    locked: false,
    prefix: [],
    subject: [{ id: "s0", text: "1girl", sep: "", origins: ["source"] }],
    suffix: [],
    dropped: [],
    character: { enabled: false, captions: [], add_male_caption: false },
    negative: [],
    model: null,
    params: {},
    use_source_vibe: false,
    flags: [],
    notes: "",
  };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  resetShelfForTests();
  window.localStorage.clear();
  api.getShelf.mockResolvedValue({ materials: [], facets: {} });
  api.searchMaterials.mockResolvedValue({ nodes: [], total: 0, has_more: false, facet_options: {} });
  api.listRecipeRuns.mockResolvedValue({ runs: [] });
  api.getExportDefaults.mockResolvedValue({ exports: [] });
  api.listWorkspaces.mockResolvedValue({ workspaces: [] });
  api.getLLMStatus.mockResolvedValue({ available: false, base_url: null, models: {} });
});

afterEach(cleanup);

describe("new recipe", () => {
  const props = {
    workspaceId: "w",
    recipeId: "new1",
    recipes: [],
    images: [],
    groups: [],
    categories: {},
    analysisReady: false,
    translateOn: false,
    onBack: vi.fn(),
    onOpenRecipe: vi.fn(),
    onUseArtistInCustom: vi.fn(),
    onSaved: vi.fn(),
    onDeleted: vi.fn(),
  };

  it("is not saved until something changes, then is created once", async () => {
    const onCreated = vi.fn();
    const draft = draftRecipe();
    api.saveNewRecipe.mockImplementation((_ws: string, recipe: Recipe) => Promise.resolve({ recipe: { ...recipe, version: 1 } }));
    render(<RecipeWorkspace {...props} onCreated={onCreated} unsaved={draft} />);

    expect(await screen.findByText(/新配方，还没保存/)).toBeTruthy();
    expect(api.getRecipe).not.toHaveBeenCalled();
    expect(api.listRecipeRuns).not.toHaveBeenCalled();
    expect(api.saveNewRecipe).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /删除/ })).toBeNull();

    fireEvent.change(screen.getByLabelText("配方名"), { target: { value: "我的配方" } });
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(api.saveNewRecipe).toHaveBeenCalledTimes(1);
    expect(api.saveNewRecipe.mock.calls[0][1].name).toBe("我的配方");
    expect(await screen.findByText("v1", { selector: ".sl-recipe-meta span" })).toBeTruthy();
    expect(api.saveRecipe).not.toHaveBeenCalled();
  });
});

describe("dropping files", () => {
  it("offers a new image group, and the current group when one is open", async () => {
    const payload = (id: string, name: string): WorkspacePayload => ({
      workspace: { id, name, kind: "files", root: "F:/x", data_dir: "F:/x", scan_dirs: [], files: [], created_at: 0, last_opened_at: 0 },
      scanned_at: 1,
      images: [],
    });
    api.createImageGroup.mockResolvedValue(payload("g2", "图片组 新"));
    api.uploadImages.mockImplementation((id: string) => Promise.resolve(payload(id, id === "g2" ? "图片组 新" : "旧组")));
    render(<CustomWorkspaceProvider><StyleLabPage /></CustomWorkspaceProvider>);

    const file = new File(["x"], "a.png", { type: "image/png" });
    const dataTransfer = { types: ["Files"], files: [file] };
    fireEvent.dragEnter(window, { dataTransfer });
    // 没打开图片组时只能新建。
    expect(screen.queryByText(/加入当前图片组/)).toBeNull();
    fireEvent.drop(screen.getByText("新建图片组", { selector: ".sl-drop-target span" }), { dataTransfer });
    await waitFor(() => expect(api.uploadImages).toHaveBeenCalledWith("g2", [file]));
    expect(api.createImageGroup).toHaveBeenCalledTimes(1);
    // 松手后投放区收起。
    expect(document.querySelector(".sl-drop-overlay")).toBeNull();

    // 打开了图片组：可以加进当前组，不新建。
    fireEvent.dragEnter(window, { dataTransfer });
    fireEvent.drop(await screen.findByText(/加入当前图片组「图片组 新」/), { dataTransfer });
    await waitFor(() => expect(api.uploadImages).toHaveBeenCalledTimes(2));
    expect(api.createImageGroup).toHaveBeenCalledTimes(1);

    // 拖出窗口也会收起。
    fireEvent.dragEnter(window, { dataTransfer });
    expect(document.querySelector(".sl-drop-overlay")).toBeTruthy();
    fireEvent.dragLeave(window, { dataTransfer });
    expect(document.querySelector(".sl-drop-overlay")).toBeNull();
  });
});
