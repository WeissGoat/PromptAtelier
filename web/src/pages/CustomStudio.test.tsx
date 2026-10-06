import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeDocument, NodeRole } from "../nodes/types";
import { CustomWorkspaceProvider, useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import { CustomStudio } from "./CustomStudio";

function node(role: NodeRole, id: string): NodeDocument {
  return { schema: "tags-machine-core.node/v1", kind: role, id, name: id, prompt: { positive: [{ text: id }], negative: [] } };
}

function Harness() {
  const workspace = useCustomWorkspace();
  function configurePrimary() {
    workspace.selectNode("primary-artist", "artists/a", node("artist", "artist-a"));
    workspace.selectNode("primary-character", "characters/homura", node("character", "homura"));
    workspace.selectNode("primary-action", "actions/standing", node("action", "standing"));
  }
  function configureMatrix() {
    configurePrimary();
    const artist = workspace.addCompare("artist");
    workspace.selectNode(artist, "artists/b", node("artist", "artist-b"));
    const action = workspace.addCompare("action");
    workspace.selectNode(action, "actions/sitting", node("action", "sitting"));
  }
  function configureBehaviorCompare() {
    const slotId = workspace.addPromptBehaviorCompare();
    workspace.renamePromptBehavior(slotId, "No Character Prompts");
    workspace.setPromptBehavior({
      ...workspace.state.promptBehaviorGroup.primary.value,
      characterPrompts: { mode: "off", addMaleCaption: false },
    });
  }
  return <><button onClick={configurePrimary}>configure primary</button><button onClick={configureMatrix}>configure matrix</button><button onClick={configureBehaviorCompare}>configure behavior compare</button><CustomStudio /></>;
}

function renderStudio() {
  render(<CustomWorkspaceProvider><Harness /></CustomWorkspaceProvider>);
}

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function batchBodies(fetchMock: ReturnType<typeof mockGeneration>) {
  return fetchMock.mock.calls
    .filter(([input]) => String(input).includes("/generate/batch"))
    .map(([, init]) => JSON.parse(String(init?.body)));
}

function mockGeneration() {
  let job = 0;
  const backgroundJobs: unknown[] = [];
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/generate/batch")) {
      const body = JSON.parse(String(init?.body));
      job += 1;
      const record = {
        id: `bg-${job}`,
        name: "generate-batch",
        status: "succeeded",
        created_at: 1_780_000_000,
        events: [],
        result: {
          label: body.label,
          kind: body.kind,
          output_dir: body.output_dir,
          total: body.items.length,
          counts: { queued: 0, running: 0, succeeded: body.items.length, failed: 0, cancelled: 0 },
          items: body.items.map((item: { label: string; seed: number; group?: number; labels?: Record<string, string> }, index: number) => ({
            index,
            label: item.label,
            seed: item.seed,
            group: item.group,
            labels: item.labels,
            status: "succeeded",
            images: [{ path: `outputs/bg-${index}.png` }],
            error: null,
          })),
        },
      };
      backgroundJobs.unshift(record);
      return response(record);
    }
    if (url.includes("/jobs?name=generate-batch")) return response({ jobs: backgroundJobs });
    if (url.includes("/compose-preview")) {
      const body = JSON.parse(String(init?.body));
      return response({
        status: "ready",
        prompt_bundle: { prompt: { positive: "composed prompt", negative: body.compose.negative } },
        render_request: { model: "nai-diffusion-4-5-full", width: body.render.width, height: body.render.height, parameters: body.render.params },
      });
    }
    if (url.includes("/results/image-metadata")) {
      const path = new URL(url).searchParams.get("path") ?? "";
      const pathParts = path.split("/");
      return response({
        schema: "tags-machine-core.web.image-metadata/v1",
        path,
        filename: pathParts[pathParts.length - 1],
        size_bytes: 1024,
        modified_at: "2026-07-12T08:00:00+00:00",
        model: "nai-diffusion-4-5-full",
        dimensions: { width: 832, height: 1216 },
        png_text: {},
        parameters: { seed: 123456, model: "nai-diffusion-4-5-full" },
      });
    }
    if (url.includes("/results/open-image-folder")) return response({ opened: true });
    throw new Error(`Unexpected request: ${url}`);
  });
}

describe("CustomStudio", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders the node workbench with an empty Negative prompt", () => {
    renderStudio();
    expect(screen.getByText("Node Editor")).toBeTruthy();
    expect(screen.getByText("Prompt & Generate")).toBeTruthy();
    expect((screen.getByLabelText("Negative prompt") as HTMLTextAreaElement).value).toBe("");
    expect(screen.queryByText("Compare", { selector: "nav *" })).toBeNull();
  });

  it("Generate Primary hands the job to the backend and shows it in the task panel", async () => {
    const fetchMock = mockGeneration();
    renderStudio();
    fireEvent.click(screen.getByText("configure primary"));
    fireEvent.change(screen.getByLabelText("NT"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate Primary" }));

    await waitFor(() => expect(batchBodies(fetchMock)).toHaveLength(1));
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/compose-preview"))).toBe(false);
    const body = batchBodies(fetchMock)[0];
    expect(body.kind).toBe("primary");
    expect(body.items).toHaveLength(1);
    expect(body.items[0].compose_request.compose.nodes.map((item: { ref: string }) => item.ref)).toEqual(["artists/a", "characters/homura", "actions/standing"]);
    expect(body.items[0].compose_request.render.params.n_samples).toBe(3);
    // 每次出图一个独立文件夹：outputs/compares/primary_<时间>_<id>/group_001_seed_<seed>
    expect(body.output_dir).toMatch(/^outputs\/compares\/primary_\d{14}_[0-9a-f]{8}$/);
    expect(body.items[0].generate.output_dir).toBe(`${body.output_dir}/group_001_seed_${body.items[0].seed}`);

    expect(await screen.findByText(/已提交：Primary · 1 轮/)).toBeTruthy();
    expect(await screen.findByText("成功 1 / 1")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: /^打开 Primary · Seed \d+ 大图$/ }));
    expect(await screen.findByRole("dialog", { name: "图片详情" })).toBeTruthy();
    expect(screen.getByText("123456")).toBeTruthy();
  });

  it("Generate Primary plans N rounds with consecutive seeds in one job", async () => {
    const fetchMock = mockGeneration();
    renderStudio();
    fireEvent.click(screen.getByText("configure primary"));
    fireEvent.change(screen.getByLabelText("N"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate Primary (2 轮)" }));

    await waitFor(() => expect(batchBodies(fetchMock)).toHaveLength(1));
    const body = batchBodies(fetchMock)[0];
    expect(body.label).toBe("Primary · 2 轮");
    expect(body.items.map((item: { seed: number }) => item.seed)).toEqual([100, 101]);
    expect(body.items[1].generate.output_dir).toBe(`${body.output_dir}/group_002_seed_101`);
    expect(await screen.findByText("Round 1 · Seed 100")).toBeTruthy();
    expect(screen.getByText("Round 2 · Seed 101")).toBeTruthy();
  });

  it("Compare Generate hands the whole matrix to the backend grouped by N", async () => {
    const fetchMock = mockGeneration();
    renderStudio();
    fireEvent.click(screen.getByText("configure matrix"));
    fireEvent.change(screen.getByLabelText("N"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "42" } });
    expect(screen.queryByLabelText("后台运行")).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Compare Generate · 8" }));

    await waitFor(() => expect(batchBodies(fetchMock)).toHaveLength(1));
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/compose-preview"))).toBe(false);
    const body = batchBodies(fetchMock)[0];
    expect(body.kind).toBe("compare");
    expect(body.label).toBe("Compare · 8 张");
    expect(body.items).toHaveLength(8);
    expect(body.items.map((item: { seed: number }) => item.seed)).toEqual([42, 42, 42, 42, 43, 43, 43, 43]);
    expect(body.items.every((item: { compose_request: { render: { params: { n_samples: number } } } }) => item.compose_request.render.params.n_samples === 1)).toBe(true);
    expect(body.items[0].generate.output_dir).toContain("group_001_seed_42");
    expect(body.items[7].generate.output_dir).toContain("group_002_seed_43");
    expect(body.items[0].label).toBe("artist-a · homura · standing · Default");
    expect(screen.getByText("Artist 2 × Character 1 × Action 2 × Behavior 1 × Groups 2 = 8")).toBeTruthy();

    expect(await screen.findByText("成功 8 / 8")).toBeTruthy();
    expect(screen.getByText("Group 1 · Seed 42")).toBeTruthy();
    expect(screen.getByText("Group 2 · Seed 43")).toBeTruthy();
    // 图下只写各项之间不同的维度，相同的写在"共同"里。
    expect(screen.getByText("共同：homura · Default")).toBeTruthy();
    expect(screen.getAllByRole("img", { name: "artist-a · standing" })).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: "打开 artist-b · sitting 大图" })[0]);
    expect(await screen.findByRole("dialog", { name: "图片详情" })).toBeTruthy();
  });

  it("Preview renders readable prompt fields and hides raw parameters by default", async () => {
    mockGeneration();
    renderStudio();
    fireEvent.click(screen.getByText("configure primary"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect((screen.getByLabelText("Positive preview") as HTMLTextAreaElement).value).toBe("composed prompt"));
    expect(screen.getByText("Model")).toBeTruthy();
    expect(screen.getByText("nai-diffusion-4-5-full")).toBeTruthy();
    expect(screen.getByText("完整生图参数")).toBeTruthy();
  });

  it("previews the active behavior but ordinary Generate uses Primary", async () => {
    const fetchMock = mockGeneration();
    renderStudio();
    fireEvent.click(screen.getByText("configure primary"));
    fireEvent.click(screen.getByText("configure behavior compare"));

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/compose-preview"))).toHaveLength(1));
    const previewCall = fetchMock.mock.calls.find(([input]) => String(input).includes("/compose-preview"));
    const previewBody = JSON.parse(String(previewCall?.[1]?.body));
    expect(previewBody.render.params.character_prompts).toBeUndefined();

    fireEvent.click(screen.getByRole("button", { name: "Generate Primary" }));
    await waitFor(() => expect(batchBodies(fetchMock)).toHaveLength(1));
    const primaryBody = batchBodies(fetchMock)[0].items[0].compose_request;
    expect(primaryBody.render.params.character_prompts).toEqual({ mode: "auto", add_male_caption: true });
  });

  it("expands prompt behavior variants in Compare Generate", async () => {
    const fetchMock = mockGeneration();
    renderStudio();
    fireEvent.click(screen.getByText("configure matrix"));
    fireEvent.click(screen.getByText("configure behavior compare"));
    fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "42" } });

    const compareButton = await screen.findByRole("button", { name: "Compare Generate · 8" });
    fireEvent.click(compareButton);

    await waitFor(() => expect(batchBodies(fetchMock)).toHaveLength(1));
    type ComposeBody = { render: { seed: number; params: Record<string, unknown> } };
    const composeRequests: ComposeBody[] = batchBodies(fetchMock)[0].items.map((item: { compose_request: ComposeBody }) => item.compose_request);
    expect(composeRequests).toHaveLength(8);
    expect(composeRequests.map((request) => request.render.seed)).toEqual(Array(8).fill(42));
    expect(composeRequests.filter((request) => request.render.params.character_prompts).length).toBe(4);
    expect(screen.getByText("Artist 2 × Character 1 × Action 2 × Behavior 2 × Groups 1 = 8")).toBeTruthy();
    expect(screen.getAllByText("Default").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No Character Prompts").length).toBeGreaterThan(0);
  });
});
