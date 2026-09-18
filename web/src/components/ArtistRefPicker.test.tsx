import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ArtistRefPicker } from "./ArtistRefPicker";

describe("ArtistRefPicker", () => {
  beforeEach(() => vi.useFakeTimers());

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("returns the selected artist ref while displaying its name", async () => {
    const onChange = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      schema: "list",
      role: "artist",
      nodes: [{ role: "artist", name: "vibe-style", ref: "F:/artists/vibe" }],
      offset: 0,
      limit: 20,
      has_more: false,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    render(<ArtistRefPicker label="Vibe Artist" onChange={onChange} value="" />);
    fireEvent.focus(screen.getByRole("combobox", { name: "Vibe Artist" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
    });
    fireEvent.mouseDown(screen.getByRole("option", { name: "vibe-style" }));

    expect(onChange).toHaveBeenCalledWith("F:/artists/vibe");
    expect((screen.getByRole("combobox", { name: "Vibe Artist" }) as HTMLInputElement).value).toBe("vibe-style");
  });
});
