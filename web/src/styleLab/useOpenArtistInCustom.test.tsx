import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { NodeReadResponse } from "../api/types";
import { CustomWorkspaceProvider, useCustomWorkspace } from "../workspace/CustomWorkspaceProvider";
import type { ArtistExport } from "./api";
import { useOpenArtistInCustom } from "./useOpenArtistInCustom";

const artist: ArtistExport = {
  folder: "1_Ink",
  path: "F:/design/画风/1_Ink",
  recipe_id: "r",
  recipe_version: 2,
  recipe_name: "配方",
  exported_at: 1_700_000_000,
  files: ["tags.txt"],
  exists: true,
};

const readResponse: NodeReadResponse = {
  schema: "tags-machine-core.web.node/v2",
  ref: artist.path,
  node: {
    schema: "tags-machine-core.node/v1",
    kind: "artist",
    id: "1_Ink",
    name: "1_Ink",
    prompt: { positive: [], negative: [] },
    renderers: { novelai: { params: { steps: 28 } } },
  },
  form: {},
  editor: {
    adapter: "legacy_artist_tags/v1",
    role: "artist",
    values: { prompt_prefix: "artist:foo" },
    sources: [],
    capabilities: {},
  },
};

function Harness({ onOpen }: { onOpen: () => void }) {
  const openArtist = useOpenArtistInCustom(onOpen);
  const workspace = useCustomWorkspace();
  return (
    <>
      <button onClick={() => void openArtist(artist)} type="button">open artist</button>
      <span data-testid="artist-ref">{workspace.state.groups.artist.primary.sourceRef ?? "empty"}</span>
      <span data-testid="artist-name">{workspace.state.groups.artist.primary.draftNode?.name ?? "empty"}</span>
    </>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(readResponse), { status: 200, headers: { "Content-Type": "application/json" } }),
  );
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("selects the exported artist in Custom and navigates there", async () => {
  const onOpen = vi.fn();
  render(<CustomWorkspaceProvider><Harness onOpen={onOpen} /></CustomWorkspaceProvider>);

  fireEvent.click(screen.getByRole("button", { name: "open artist" }));

  await waitFor(() => expect(onOpen).toHaveBeenCalledTimes(1));
  expect(screen.getByTestId("artist-ref").textContent).toBe(artist.path);
  expect(screen.getByTestId("artist-name").textContent).toBe("1_Ink");
  const url = String(vi.mocked(globalThis.fetch).mock.calls[0][0]);
  expect(url).toContain("/nodes/read?");
  expect(url).toContain(`ref=${encodeURIComponent(artist.path)}`);
  expect(url).toContain("role=artist");
});
