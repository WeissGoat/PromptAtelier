import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CustomStudio } from "./CustomStudio";

describe("CustomStudio", () => {
  it("renders node selectors and prompt preview", () => {
    render(<CustomStudio />);

    expect(screen.getByText("Artist")).toBeTruthy();
    expect(screen.getByText("Character")).toBeTruthy();
    expect(screen.getByText("Action")).toBeTruthy();
    expect(screen.getByText("Prompt Preview")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Preview" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Generate" })).toBeTruthy();
  });

  it("uses an explicitly selected artist ref in the preview request", async () => {
    const artist = { role: "artist", name: "20260412", ref: "F:/design/??/20260412" };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ schema: "list", role: "artist", nodes: [artist] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "ready", prompt_bundle: { prompt: { positive: "", negative: "" } } }), { status: 200 }));

    render(<CustomStudio />);
    fireEvent.click(screen.getByRole("button", { name: "Load Artist nodes" }));
    await screen.findByRole("option", { name: "20260412 F:/design/??/20260412" });
    fireEvent.click(screen.getByRole("option", { name: "20260412 F:/design/??/20260412" }));
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const request = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(request.render.artist).toBe(artist.ref);
    expect(request.compose.nodes).toContainEqual({ role: "artist", ref: artist.ref });
});
