import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeDocument, NodeRole } from "../nodes/types";
import { CustomStudio } from "./CustomStudio";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function node(role: NodeRole, positive: string): NodeDocument {
  return {
    schema: "tags-machine-core.node/v1",
    kind: role,
    id: `temporary-${role}`,
    prompt: { positive: [{ text: positive }], negative: [] },
  };
}

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/nodes?")) {
      return response({
        schema: "list",
        role: "artist",
        nodes: [{ role: "artist", name: "source artist", ref: "F:/nodes/artist" }],
      });
    }
    if (url.includes("/nodes/read")) {
      return response({
        schema: "node",
        ref: "F:/nodes/artist",
        node: node("artist", "source_artist"),
        form: {},
      });
    }
    if (url.includes("/nodes/preview")) {
      return response({ node: JSON.parse(String(init?.body)).node });
    }
    if (url.includes("/compose-preview")) {
      return response({
        status: "ready",
        prompt_bundle: { prompt: { positive: "composed prompt", negative: "lowres" } },
        render_request: { backend: "novelai", prompt: "composed prompt", negative_prompt: "lowres" },
      });
    }
    if (url.includes("/generate")) {
      return response({ id: "job-1", name: "job-1", status: "queued" });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
}

function callsFor(fetchMock: ReturnType<typeof mockApi>, path: string) {
  return fetchMock.mock.calls.filter(([input]) => String(input).includes(path));
}

async function applyTemporaryNode(role: NodeRole, draft: NodeDocument) {
  fireEvent.click(screen.getByRole("button", { name: `新建空白${role === "character" ? "Character" : role === "action" ? "Action" : "Artist"}节点` }));
  fireEvent.click(screen.getByRole("button", { name: `编辑${role === "character" ? "Character" : role === "action" ? "Action" : "Artist"}节点` }));
  const editor = await screen.findByLabelText("节点 JSON");
  fireEvent.change(editor, { target: { value: JSON.stringify(draft) } });
  fireEvent.click(screen.getByRole("button", { name: "应用到本次运行" }));
  await waitFor(() => expect(screen.queryByLabelText("节点 JSON")).toBeNull());
}

describe("CustomStudio", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders node slots and prompt preview", () => {
    render(<CustomStudio />);

    expect(screen.getByText("Artist")).toBeTruthy();
    expect(screen.getByText("Character")).toBeTruthy();
    expect(screen.getByText("Action")).toBeTruthy();
    expect(screen.getByText("Prompt Preview")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Preview" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Generate" })).toBeTruthy();
  });

  it("previews inline modified character and artist nodes", async () => {
    const fetchMock = mockApi();
    render(<CustomStudio />);

    await applyTemporaryNode("character", node("character", "1girl, black_hair"));
    await applyTemporaryNode("artist", node("artist", "watercolor_style"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(1));
    const request = JSON.parse(String(callsFor(fetchMock, "/compose-preview")[0][1]?.body));
    expect(request.render.artist).toBeUndefined();
    expect(request.compose.nodes).toContainEqual({
      role: "character",
      ref: "web-temporary:character:temporary-character",
      node: node("character", "1girl, black_hair"),
    });
    expect(request.compose.nodes).toContainEqual({
      role: "artist",
      ref: "web-temporary:artist:temporary-artist",
      node: node("artist", "watercolor_style"),
    });
  });

  it("uses an inline modified library artist instead of its source ref", async () => {
    const fetchMock = mockApi();
    render(<CustomStudio />);

    await applyTemporaryNode("character", node("character", "1girl"));
    fireEvent.click(screen.getByRole("button", { name: "Load Artist nodes" }));
    const option = await screen.findByRole("option", { name: "source artist F:/nodes/artist" });
    fireEvent.click(option);
    await waitFor(() => expect(callsFor(fetchMock, "/nodes/read")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "编辑Artist节点" }));
    const editor = await screen.findByLabelText("节点 JSON");
    fireEvent.change(editor, { target: { value: JSON.stringify(node("artist", "draft_artist")) } });
    fireEvent.click(screen.getByRole("button", { name: "应用到本次运行" }));
    await waitFor(() => expect(screen.queryByLabelText("节点 JSON")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(1));
    const request = JSON.parse(String(callsFor(fetchMock, "/compose-preview")[0][1]?.body));
    expect(request.render.artist).toBeUndefined();
    expect(request.compose.nodes).toContainEqual({
      role: "artist",
      ref: "F:/nodes/artist",
      node: node("artist", "draft_artist"),
    });
  });

  it("previews an inline blank-origin action node", async () => {
    const fetchMock = mockApi();
    render(<CustomStudio />);

    await applyTemporaryNode("action", node("action", "standing, looking_at_viewer"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(1));
    const request = JSON.parse(String(callsFor(fetchMock, "/compose-preview")[0][1]?.body));
    expect(request.compose.nodes).toContainEqual({
      role: "action",
      ref: "web-temporary:action:temporary-action",
      node: node("action", "standing, looking_at_viewer"),
    });
  });

  it("re-previews before generate after a draft changes", async () => {
    const fetchMock = mockApi();
    render(<CustomStudio />);

    await applyTemporaryNode("character", node("character", "1girl"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "编辑Character节点" }));
    const editor = await screen.findByLabelText("节点 JSON");
    fireEvent.change(editor, { target: { value: JSON.stringify(node("character", "1boy")) } });
    fireEvent.click(screen.getByRole("button", { name: "应用到本次运行" }));
    await waitFor(() => expect(screen.queryByLabelText("节点 JSON")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(2));
    await waitFor(() => expect(callsFor(fetchMock, "/generate")).toHaveLength(1));
    const request = JSON.parse(String(callsFor(fetchMock, "/compose-preview")[1][1]?.body));
    expect(request.compose.nodes[0].node.prompt.positive).toEqual([{ text: "1boy" }]);
  });

  it("re-previews before generate after negative prompt changes", async () => {
    const fetchMock = mockApi();
    render(<CustomStudio />);

    await applyTemporaryNode("character", node("character", "1girl"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("Negative prompt"), { target: { value: "new negative" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(2));
    await waitFor(() => expect(callsFor(fetchMock, "/generate")).toHaveLength(1));
    const request = JSON.parse(String(callsFor(fetchMock, "/compose-preview")[1][1]?.body));
    expect(request.compose.negative).toBe("new negative");
  });

  it("ignores a delayed preview after a render parameter changes", async () => {
    const pendingPreview = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/nodes/preview")) {
        return Promise.resolve(response({ node: JSON.parse(String(init?.body)).node }));
      }
      if (url.includes("/compose-preview")) return pendingPreview.promise;
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<CustomStudio />);

    await applyTemporaryNode("character", node("character", "1girl"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("Negative prompt"), { target: { value: "new negative" } });
    pendingPreview.resolve(response({
      status: "ready",
      prompt_bundle: { prompt: { positive: "stale prompt", negative: "stale negative" } },
      render_request: { backend: "novelai", prompt: "stale prompt" },
    }));

    await waitFor(() => expect(screen.getByText("Preview stale")).toBeTruthy());
    expect((screen.getByLabelText("Positive preview") as HTMLTextAreaElement).value).toBe("");
    expect((screen.getByLabelText("Negative preview") as HTMLTextAreaElement).value).toBe("new negative");
  });

  it("does not generate from a stale automatic preview", async () => {
    const pendingPreview = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/nodes/preview")) {
        return Promise.resolve(response({ node: JSON.parse(String(init?.body)).node }));
      }
      if (url.includes("/compose-preview")) return pendingPreview.promise;
      if (url.includes("/generate")) return Promise.resolve(response({ id: "job-1", name: "job-1", status: "queued" }));
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<CustomStudio />);

    await applyTemporaryNode("character", node("character", "1girl"));
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "42" } });
    pendingPreview.resolve(response({
      status: "ready",
      prompt_bundle: { prompt: { positive: "stale prompt", negative: "lowres" } },
      render_request: { backend: "novelai", prompt: "stale prompt" },
    }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("输入已变化，请重新生成"));
    expect(callsFor(fetchMock, "/generate")).toHaveLength(0);
  });

  it("blocks generation for a fully empty temporary node", () => {
    const fetchMock = mockApi();
    render(<CustomStudio />);

    fireEvent.click(screen.getByRole("button", { name: "新建空白Character节点" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    expect(screen.getByRole("alert").textContent).toContain("Character 节点的临时 prompt 不能为空");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("never calls nodes/save during preview or generate", async () => {
    const fetchMock = mockApi();
    render(<CustomStudio />);

    await applyTemporaryNode("character", node("character", "1girl"));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(callsFor(fetchMock, "/compose-preview")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(callsFor(fetchMock, "/generate")).toHaveLength(1));

    expect(callsFor(fetchMock, "/nodes/save")).toHaveLength(0);
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });
});
