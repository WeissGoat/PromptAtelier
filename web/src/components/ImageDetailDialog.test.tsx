import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImageDetailDialog } from "./ImageDetailDialog";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function metadata() {
  return {
    schema: "tags-machine-core.web.image-metadata/v1",
    path: "F:/outputs/generated.png",
    filename: "generated.png",
    size_bytes: 2048,
    modified_at: "2026-07-12T08:00:00+00:00",
    model: "nai-diffusion-4-5-full",
    dimensions: { width: 832, height: 1216 },
    png_text: { Source: "NovelAI V4.5" },
    parameters: {
      seed: 998877,
      model: "nai-diffusion-4-5-full",
      sampler: "k_euler",
      steps: 28,
      scale: 5,
      prompt: "actual png prompt",
      uc: "actual png negative",
    },
  };
}

describe("ImageDetailDialog", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("displays metadata read by the image metadata API and opens the containing folder", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/results/image-metadata")) return response(metadata());
      if (url.includes("/results/open-image-folder")) return response({ opened: true });
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ImageDetailDialog initialIndex={0} onClose={vi.fn()} paths={["outputs/generated.png"]} />);

    expect(await screen.findByText("998877")).toBeTruthy();
    expect(screen.getByText("832 × 1216")).toBeTruthy();
    expect(screen.getByText("nai-diffusion-4-5-full")).toBeTruthy();
    expect((screen.getByLabelText("Prompt") as HTMLTextAreaElement).value).toBe("actual png prompt");
    expect(screen.getByRole("img", { name: "generated.png" }).getAttribute("src")).toContain("/results/image?path=outputs%2Fgenerated.png");

    fireEvent.click(screen.getByRole("button", { name: "打开所在文件夹" }));
    await waitFor(() => expect(screen.getByText("已在资源管理器中定位图片")).toBeTruthy());
    const folderCall = fetchMock.mock.calls.find(([input]) => String(input).includes("/results/open-image-folder"));
    expect(folderCall?.[1]?.method).toBe("POST");
    expect(JSON.parse(String(folderCall?.[1]?.body))).toEqual({ path: "outputs/generated.png" });
  });

  it("closes with Escape or by clicking the backdrop", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response(metadata()));
    const onClose = vi.fn();
    const { container } = render(<ImageDetailDialog initialIndex={0} onClose={onClose} paths={["outputs/generated.png"]} />);
    await screen.findByText("998877");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.mouseDown(container.querySelector(".image-detail-backdrop") as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("navigates within bounds and shows a folded tag-level diff at the bottom", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/results/image-parameter-diff")) {
        return response({
          schema: "tags-machine-core.web.image-parameter-diff/v1",
          previous: { path: "F:/outputs/first.png", filename: "first.png" },
          current: { path: "F:/outputs/second.png", filename: "second.png" },
          match: false,
          diff_count: 4,
          diffs: [
            {
              path: "$.input",
              kind: "value",
              left: "official style, anime coloring, monochrome",
              right: "official style, anime coloring, compare_edit_marker, monochrome",
            },
            {
              path: "$.parameters.v4_prompt.caption.base_caption",
              kind: "value",
              left: "official style, anime coloring, monochrome",
              right: "official style, anime coloring, compare_edit_marker, monochrome",
            },
            { path: "$.parameters.sampler", kind: "value", left: "k_euler", right: "k_euler_ancestral" },
            { path: "$.parameters.new_setting", kind: "key", left: "<missing>", right: true },
          ],
          previous_normalized: {},
          current_normalized: {},
        });
      }
      if (url.includes("/results/image-metadata")) {
        const path = new URL(url).searchParams.get("path");
        return response({
          ...metadata(),
          path: `F:/${path}`,
          filename: path?.includes("second") ? "second.png" : "first.png",
          parameters: { ...metadata().parameters, seed: path?.includes("second") ? 222 : 111 },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<ImageDetailDialog initialIndex={0} onClose={vi.fn()} paths={["outputs/first.png", "outputs/second.png"]} />);

    expect(await screen.findByText("1 / 2")).toBeTruthy();
    expect((screen.getByRole("button", { name: "上一张图片" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "下一张图片" }) as HTMLButtonElement).disabled).toBe(false);
    const firstDiffButton = screen.getByRole("button", { name: /参数 Diff/ });
    expect(firstDiffButton.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "下一张图片" }));
    expect(await screen.findByText("2 / 2")).toBeTruthy();
    expect(await screen.findByText("3 项")).toBeTruthy();

    const diffPanel = screen.getByText("参数 Diff").closest(".parameter-diff-panel") as HTMLElement;
    const pngTextPanel = screen.getByText("全部 PNG Text").closest("details") as HTMLDetailsElement;
    const diffButton = screen.getByRole("button", { name: /参数 Diff/ });
    expect(diffButton.getAttribute("aria-expanded")).toBe("false");
    expect(pngTextPanel.compareDocumentPosition(diffPanel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(diffButton);
    expect(diffButton.getAttribute("aria-expanded")).toBe("true");
    const summary = diffPanel.querySelector(".parameter-diff-overview") as HTMLElement;
    expect(summary.textContent).toContain("compare_edit_marker");
    expect(summary.textContent).not.toContain("official style, anime coloring, monochrome");
    expect(summary.querySelectorAll(".prompt-diff-summary")).toHaveLength(1);
    expect(summary.textContent).toContain("sampler");
    expect(summary.textContent).toContain("k_euler_ancestral");
    expect(summary.textContent).toContain("new setting");
    expect((screen.getByRole("button", { name: "下一张图片" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(await screen.findByText("1 / 2")).toBeTruthy();
  });
});
