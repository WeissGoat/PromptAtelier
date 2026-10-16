import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SourceFilesPanel } from "./SourceFilesPanel";

function response(data: unknown): Response {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("SourceFilesPanel", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("edits a raw source file and saves it through the diff preview", async () => {
    const saved = { schema: "tags-machine-core.web.node/v2", ref: "/n", node: { id: "n" }, form: {} };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/nodes/source-files")) {
        return response({ schema: "files", ref: "/n", files: [
          { name: "tags.txt", path: "/n/tags.txt", format: "txt", sha256: "x", text: "standing,\r\nsmile\r\n" },
          { name: "classify.yaml", path: "/n/classify.yaml", format: "yaml", sha256: "y", text: "phase: core\n" },
        ] });
      }
      if (url.includes("/nodes/source-save-preview")) {
        const body = JSON.parse(String(init?.body));
        expect(body.files).toEqual([{ name: "tags.txt", text: "standing,\nsmile, wink\n" }]);
        return response({ schema: "preview", preview_id: "save_1", node: {}, warnings: [], expires_at: 0, files: [
          { path: "/n/tags.txt", relative: "tags.txt", format: "txt", before_sha256: "x", changed: true, diff: "+smile, wink", after_text: "" },
        ] });
      }
      if (url.includes("/nodes/save-commit")) return response(saved);
      throw new Error(`Unexpected request: ${url}`);
    });
    const onSaved = vi.fn();
    render(<SourceFilesPanel hasUnsavedDraft={false} nodeRef="/n" onSaved={onSaved} role="action" />);

    const editor = await screen.findByLabelText("源文件 tags.txt") as HTMLTextAreaElement;
    // CRLF 在浏览器里按 \n 显示，没改动时不算脏。
    expect(editor.value).toBe("standing,\nsmile\n");
    expect((screen.getByRole("button", { name: /保存源文件/ }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(editor, { target: { value: "standing,\nsmile, wink\n" } });
    fireEvent.click(screen.getByRole("button", { name: /保存源文件 \(1\)/ }));
    expect(await screen.findByRole("dialog", { name: "保存节点源文件 Diff" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "确认写入 1 个文件" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/nodes/source-files"))).toHaveLength(2);
  });
});
