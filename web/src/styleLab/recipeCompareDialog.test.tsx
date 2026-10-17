import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Recipe, RecipeSummary } from "./api";

const api = vi.hoisted(() => ({ getRecipe: vi.fn(), getRecipeVersion: vi.fn() }));

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return { ...actual, ...api };
});

import { RecipeCompareDialog } from "./RecipeCompare";

function recipe(id: string, version: number, prefix: string, overrides: Partial<Recipe> = {}): Recipe {
  return {
    schema: "tags-machine-core.style-lab.recipe/v1",
    id,
    name: `配方 ${id}`,
    version,
    created_at: 0,
    updated_at: version,
    source_image_id: null,
    group_id: null,
    stage: "edit",
    locked: true,
    prefix: [{ id: `${id}-p`, text: prefix, sep: "", origins: ["source"] }],
    subject: [],
    suffix: [],
    dropped: [],
    character: { enabled: false, captions: [], add_male_caption: false },
    negative: [],
    model: "nai-diffusion-5-full",
    params: { steps: 28 },
    use_source_vibe: false,
    flags: [],
    notes: "",
    ...overrides,
  };
}

const recipes: RecipeSummary[] = [
  { id: "a", name: "配方 a", version: 2, stage: "edit", locked: true, source_image_id: null, group_id: null, updated_at: 2 },
  { id: "b", name: "配方 b", version: 1, stage: "edit", locked: true, source_image_id: null, group_id: null, updated_at: 1 },
];

beforeEach(() => {
  api.getRecipe.mockReset();
  api.getRecipeVersion.mockReset();
  api.getRecipe.mockImplementation((_ws: string, id: string) =>
    Promise.resolve(
      id === "a"
        ? { recipe: recipe("a", 2, "0.6::ixy::, flat color"), history: [{ version: 1, updated_at: 1 }] }
        : { recipe: recipe("b", 1, "0.8::ixy::, thick lines", { params: { steps: 23 } }), history: [] },
    ),
  );
  api.getRecipeVersion.mockResolvedValue({ recipe: recipe("a", 1, "0.6::ixy::") });
});

afterEach(cleanup);

describe("RecipeCompareDialog", () => {
  it("compares two recipes tag by tag, swaps sides and picks older versions", async () => {
    render(
      <RecipeCompareDialog
        initial={{ left: { id: "a", version: null }, right: { id: "b", version: null } }}
        onClose={vi.fn()}
        recipes={recipes}
        workspaceId="w"
      />,
    );
    expect((await screen.findByTitle("只在 A")).textContent).toBe("flat color");
    expect(screen.getByTitle("只在 B").textContent).toBe("thick lines");
    expect(screen.getAllByTitle("权重 0.6 → 0.8")).toHaveLength(2);
    expect(screen.getByText("画风不同")).toBeTruthy();
    expect(screen.getByRole("cell", { name: "参数 steps" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "左右互换" }));
    expect((await screen.findByTitle("只在 A")).textContent).toBe("thick lines");

    // B 换成配方 a 的 v1：和当前的 a 比，只差 flat color。
    fireEvent.click(screen.getByRole("button", { name: "左右互换" }));
    fireEvent.change(screen.getByRole("combobox", { name: "配方 B" }), { target: { value: "a" } });
    fireEvent.change(await screen.findByRole("combobox", { name: "配方 B 的版本" }), { target: { value: "1" } });
    expect((await screen.findByTitle("只在 A")).textContent).toBe("flat color");
    expect(api.getRecipeVersion).toHaveBeenCalledWith("w", "a", 1);
    expect(screen.getAllByText("另有 1 个相同")).toHaveLength(2);
  });
});
