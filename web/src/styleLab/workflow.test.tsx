import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CustomGroups, ImageRecord, RecipeSummary, TestPlan } from "./api";

const api = vi.hoisted(() => ({ saveCustomGroups: vi.fn(), createTestPlan: vi.fn(), startTestPlan: vi.fn(), listTestPlans: vi.fn() }));
vi.mock("./api", async (original) => ({ ...await original<typeof import("./api")>(), ...api }));
import { CustomGroupsDialog } from "./CustomGroupsDialog";
import { TestPlansDialog } from "./TestPlansDialog";
import { EMPTY_CUSTOM_GROUPS, customImageIds, newCustomGroup, recipesInGroup } from "./customGroups";
import { GroupPanel } from "./GroupPanel";

const image: ImageRecord = {
  id: "image1", path: "F:/corpus/a.png", rel_path: "a.png", size_bytes: 1, mtime_ns: 1, post: null,
  width: 64, height: 96, has_metadata: true, source_label: "NovelAI", model: "nai-diffusion-4-5-full",
  request_type: "PromptGenerateRequest", prompt: "artist:foo, 1girl", negative_prompt: "", char_captions: [],
  seed: 42, steps: 28, scale: 5, cfg_rescale: 0, sampler: "k_euler_ancestral", noise_schedule: "karras",
  vibe: { count: 0, hashes: [], strengths: [], information_extracted: [] }, flags: [],
};
const recipes: RecipeSummary[] = ["r1", "r2"].map((id) => ({ id, name: `配方 ${id}`, version: 1,
  stage: "edit", locked: true, source_image_id: image.id, group_id: null, updated_at: 1,
  source_group: { kind: "custom", id: id === "r1" ? "cg_child" : "cg_other" }, preparation: { status: "ready" } }));
function plan(status = "draft"): TestPlan {
  return { id: "test1", status, created_at: 1, job_id: null, recipe_ids: ["r1"], recipes: { r1: { name: "配方 r1", hash: "hash" } },
    shelf: { materials: [], facets: {} }, missing_variants: status === "awaiting_content" ? ["r1"] : [], estimated_count: 2, reuse_count: 0,
    items: [{ id: "i1", recipe_id: "r1", label: "原参重生", kind: "regenerate", status: "pending", preview: { prompt: "1girl", negative_prompt: "", seed: 42, size: { width: 64, height: 96 }, model: "nai-diffusion-4-5-full" } }] };
}
beforeEach(() => { Object.values(api).forEach((fn) => fn.mockReset()); api.listTestPlans.mockResolvedValue({ plans: [] }); });
afterEach(cleanup);

describe("persistent custom groups", () => {
  it("allows selecting custom grouping even for loose images", () => {
    const mode = vi.fn();
    render(<GroupPanel analysis={null} analyzing={null} llmAvailable={false} mode="custom" postBuckets={[]} monthBuckets={[]}
      selectedGroup={null} recipes={[]} onChangeMode={mode} onSelectGroup={vi.fn()} onOpenRecipe={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "自定义" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText(/尚未建立自定义分组/)).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "投稿" })).toBeNull();
  });

  it("creates a group, moves selected images and saves without starting a test", async () => {
    api.saveCustomGroups.mockImplementation((_ws, doc) => Promise.resolve({ ...doc, revision: 1 }));
    const onSaved = vi.fn();
    render(<CustomGroupsDialog workspaceId="w" document={EMPTY_CUSTOM_GROUPS} images={[image]} initialGroup={null} onSaved={onSaved} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("新组名称"), { target: { value: "线条风格" } });
    fireEvent.click(screen.getByRole("button", { name: "新建组" }));
    const groupId = (screen.getByLabelText("目标组") as HTMLSelectElement).options[1].value;
    fireEvent.click(screen.getByLabelText("选择 a.png"));
    fireEvent.change(screen.getByLabelText("目标组"), { target: { value: groupId } });
    fireEvent.click(screen.getByRole("button", { name: "移动勾选的 1 张" }));
    fireEvent.click(screen.getByRole("button", { name: "保存自定义分组" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(api.saveCustomGroups.mock.calls[0][1].membership).toEqual({ image1: groupId });
    expect(api.createTestPlan).not.toHaveBeenCalled();
    expect(api.startTestPlan).not.toHaveBeenCalled();
  });

  it("renames without changing identity and resolves parent membership independently of automatic groups", async () => {
    const parent = { ...newCustomGroup("主类"), id: "cg_parent" };
    const child = { ...newCustomGroup("子类", "cg_parent"), id: "cg_child" };
    const doc: CustomGroups = { ...EMPTY_CUSTOM_GROUPS, revision: 3, groups: [parent, child], membership: { image1: child.id } };
    expect(customImageIds(doc, parent.id)).toEqual([image.id]);
    expect(recipesInGroup(recipes, doc, parent.id).map((recipe) => recipe.id)).toEqual(["r1"]);
    api.saveCustomGroups.mockResolvedValue(doc);
    render(<CustomGroupsDialog workspaceId="w" document={doc} images={[image]} initialGroup={child.id} onSaved={vi.fn()} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("组名"), { target: { value: "人工改名" } });
    fireEvent.click(screen.getByRole("button", { name: "保存自定义分组" }));
    await waitFor(() => expect(api.saveCustomGroups).toHaveBeenCalled());
    const saved = api.saveCustomGroups.mock.calls[0][1];
    expect(saved.groups.find((group: { id: string }) => group.id === child.id).name).toBe("人工改名");
    expect(saved.membership).toEqual(doc.membership);
    expect(saved.revision).toBe(3);
  });
});

describe("explicit test selection", () => {
  it("does not create or start anything on open, then previews only selected recipes", async () => {
    api.createTestPlan.mockResolvedValue(plan());
    api.startTestPlan.mockResolvedValue(plan("succeeded"));
    render(<TestPlansDialog workspaceId="w" recipes={recipes} initialIds={["r1"]} onClose={vi.fn()} />);
    expect(api.createTestPlan).not.toHaveBeenCalled();
    expect(api.startTestPlan).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "预览测试计划" }));
    await waitFor(() => expect(api.createTestPlan).toHaveBeenCalledWith("w", ["r1"], true));
    expect(api.startTestPlan).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "开始测试生图" }));
    await waitFor(() => expect(api.startTestPlan).toHaveBeenCalledWith("w", "test1"));
  });

  it("blocks start while material variants are unprepared and offers the exact Agent task", async () => {
    api.createTestPlan.mockResolvedValue(plan("awaiting_content"));
    render(<TestPlansDialog workspaceId="w" recipes={recipes} initialIds={["r2"]} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "预览测试计划" }));
    expect((await screen.findByRole("button", { name: "开始测试生图" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Agent 测试任务") as HTMLTextAreaElement).value).toContain("r2");
    expect(api.startTestPlan).not.toHaveBeenCalled();
  });
});
