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
  });

  it("Compare Generate expands 2 Artist × 1 Character × 2 Action into four one-sample jobs", async () => {
    const fetchMock = mockGeneration();
    renderStudio();
    fireEvent.click(screen.getByText("configure matrix"));
    const compareButton = await screen.findByRole("button", { name: "Compare Generate · 4" });
    fireEvent.click(compareButton);

    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/generate"))).toHaveLength(4));
    const composeCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes("/compose-preview"));
    expect(composeCalls).toHaveLength(4);
    expect(composeCalls.every(([, init]) => JSON.parse(String(init?.body)).render.params.n_samples === 1)).toBe(true);
    const seeds = composeCalls.map(([, init]) => JSON.parse(String(init?.body)).render.seed);
    expect(new Set(seeds).size).toBe(1);
    expect(seeds[0]).toBeGreaterThanOrEqual(0);
    await waitFor(() => expect(screen.getByText("成功 4")).toBeTruthy());
    expect(screen.getAllByRole("img", { name: /Compare image/ })).toHaveLength(4);
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
