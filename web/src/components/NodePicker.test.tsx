import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NodePicker } from "./NodePicker";

function response(nodes: Array<{ role: string; name: string; ref: string; relative?: string }>): Response {
  return new Response(JSON.stringify({ schema: "list", role: "action", nodes }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPicker(onSelect = vi.fn()) {
  render(<NodePicker label="Action" onClear={vi.fn()} onSelect={onSelect} placeholder="搜索" role="action" value="" />);
  return onSelect;
}

async function runSearchDebounce() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300);
  });
}

describe("NodePicker", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("loads at most six filename-only results on focus", async () => {
    vi.useFakeTimers();
    const nodes = Array.from({ length: 8 }, (_, index) => ({ role: "action", name: `node-${index}`, ref: `F:/path/${index}`, relative: `group/node-${index}` }));
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response(nodes));
    renderPicker();
    fireEvent.focus(screen.getByRole("combobox", { name: "Action" }));
    await runSearchDebounce();
    expect(screen.getAllByRole("option")).toHaveLength(6);
    expect(String(fetchMock.mock.calls[0][0])).toContain("limit=6");
    expect(screen.queryByText("group/node-0")).toBeNull();
    expect(screen.queryByText("F:/path/0")).toBeNull();
  });

  it("debounces typed queries by 300ms", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response([]));
    renderPicker();
    const input = screen.getByRole("combobox", { name: "Action" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "foot" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299);
    });
    expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("q=foot");
  });

  it("selects the exact result and closes", async () => {
    vi.useFakeTimers();
    const onSelect = renderPicker();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response([{ role: "action", name: "standing", ref: "F:/exact" }]));
    fireEvent.focus(screen.getByRole("combobox", { name: "Action" }));
    await runSearchDebounce();
    fireEvent.mouseDown(screen.getByRole("option", { name: "standing" }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ ref: "F:/exact" }));
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("closes on Escape and outside pointer down", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response([]));
    renderPicker();
    const input = screen.getByRole("combobox", { name: "Action" });
    fireEvent.focus(input);
    await runSearchDebounce();
    expect(screen.getByRole("listbox")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.focus(input);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("ignores a stale response from an older query", async () => {
    vi.useFakeTimers();
    let resolveFirst!: (value: Response) => void;
    const first = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(response([{ role: "action", name: "new-result", ref: "new" }]));
    renderPicker();
    const input = screen.getByRole("combobox", { name: "Action" });
    fireEvent.focus(input);
    await runSearchDebounce();
    fireEvent.change(input, { target: { value: "new" } });
    await runSearchDebounce();
    expect(screen.getByRole("option", { name: "new-result" })).toBeTruthy();
    await act(async () => {
      resolveFirst(response([{ role: "action", name: "old-result", ref: "old" }]));
      await Promise.resolve();
    });
    expect(screen.queryByRole("option", { name: "old-result" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
