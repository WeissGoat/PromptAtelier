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
  return <><button onClick={configurePrimary}>configure primary</button><button onClick={configureMatrix}>configure matrix</button><CustomStudio /></>;
}

function renderStudio() {
  render(<CustomWorkspaceProvider><Harness /></CustomWorkspaceProvider>);
}

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function mockGeneration() {
  let job = 0;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/compose-preview")) {
      const body = JSON.parse(String(init?.body));
      return response({
        status: "ready",
        prompt_bundle: { prompt: { positive: "composed prompt", negative: body.compose.negative } },
        render_request: { model: "nai-diffusion-4-5-full", width: body.render.width, height: body.render.height, parameters: body.render.params },
      });
    }
    if (url.includes("/generate")) {
      job += 1;
      return response({ id: `job-${job}`, name: "generate", status: "succeeded", result: { images: [{ path: `outputs/${job}.png`, meta: { seed: job } }] } });
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

  it("ordinary Generate uses primary nodes and the configured NT", async () => {
    const fetchMock = mockGeneration();
    renderStudio();
    fireEvent.click(screen.getByText("configure primary"));
    fireEvent.change(screen.getByLabelText("NT"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /^Generate$/ }));

    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/generate"))).toHaveLength(1));
    const compose = fetchMock.mock.calls.find(([input]) => String(input).includes("/compose-preview"));
    const body = JSON.parse(String(compose?.[1]?.body));
    expect(body.compose.nodes.map((item: { ref: string }) => item.ref)).toEqual(["artists/a", "characters/homura", "actions/standing"]);
    expect(body.render.params.n_samples).toBe(3);
    expect(await screen.findByRole("img", { name: "Generated image 1" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "打开 Generated image 1 大图" }));
    expect(await screen.findByRole("dialog", { name: "图片详情" })).toBeTruthy();
    expect(screen.getByText("123456")).toBeTruthy();
  });

  it("Compare Generate repeats the full matrix for every NT group", async () => {
    const fetchMock = mockGeneration();
    renderStudio();
    fireEvent.click(screen.getByText("configure matrix"));
    fireEvent.change(screen.getByLabelText("NT"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "42" } });
    const compareButton = await screen.findByRole("button", { name: "Compare Generate · 8" });
    fireEvent.click(compareButton);

    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/generate"))).toHaveLength(8));
    const composeCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes("/compose-preview"));
    expect(composeCalls).toHaveLength(8);
    expect(composeCalls.every(([, init]) => JSON.parse(String(init?.body)).render.params.n_samples === 1)).toBe(true);
    const seeds = composeCalls.map(([, init]) => JSON.parse(String(init?.body)).render.seed);
    expect(seeds.slice(0, 4)).toEqual([42, 42, 42, 42]);
    expect(seeds.slice(4)).toEqual([43, 43, 43, 43]);
    const generateCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes("/generate"));
    const outputDirs = generateCalls.map(([, init]) => JSON.parse(String(init?.body)).output_dir);
    expect(outputDirs.slice(0, 4).every((dir) => String(dir).includes("group_001_seed_42"))).toBe(true);
    expect(outputDirs.slice(4).every((dir) => String(dir).includes("group_002_seed_43"))).toBe(true);
    expect(screen.getByText("Artist 2 × Character 1 × Action 2 × Groups 2 = 8")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("成功 8")).toBeTruthy());
    expect(screen.getByText("Group 1 · Seed 42")).toBeTruthy();
    expect(screen.getByText("Group 2 · Seed 43")).toBeTruthy();
    expect(screen.getAllByRole("img", { name: /Compare image/ })).toHaveLength(8);
    fireEvent.click(screen.getAllByRole("button", { name: "打开 Compare image 1 大图" })[0]);
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
});
