import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompareWorkspaceProvider } from "../compare/CompareWorkspaceProvider";
import type { BaseTemplate, PromptVariant } from "../compare/types";
import { VariantCard } from "./VariantCard";

const template: BaseTemplate = {
  prompt: "1girl, solo",
  negative: "lowres",
  seed: 123456,
  width: 512,
  height: 512,
  steps: 28,
  scale: 5.0,
};

const variantWithImage: PromptVariant = {
  id: "var-test",
  name: "Variant Test",
  prompt: "1girl, solo, smile",
  diff: { added: ["smile"], removed: [], unchanged: ["1girl", "solo"], tokens: [] },
  seedOverride: null,
  status: "succeeded",
  jobId: "job-1",
  resultImage: {
    path: "outputs/variant_result.png",
    url: "/api/results/image?path=outputs%2Fvariant_result.png",
    seed: 123456,
  },
};

describe("VariantCard", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders open folder button and invokes /results/open-image-folder when clicked", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/results/open-image-folder")) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ opened: true }),
        } as Response;
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <CompareWorkspaceProvider>
        <VariantCard
          canDelete={true}
          isBusy={false}
          isSelectedForCompare={false}
          onRun={vi.fn()}
          onToggleCompare={vi.fn()}
          roundId="round-1"
          template={template}
          variant={variantWithImage}
        />
      </CompareWorkspaceProvider>,
    );

    const openFolderBtn = screen.getByRole("button", { name: /打开文件夹/ });
    expect(openFolderBtn).toBeTruthy();

    fireEvent.click(openFolderBtn);

    await waitFor(() => {
      const folderCall = fetchMock.mock.calls.find(([input]) =>
        String(input).includes("/results/open-image-folder"),
      );
      expect(folderCall).toBeTruthy();
      expect(folderCall?.[1]?.method).toBe("POST");
      expect(JSON.parse(String(folderCall?.[1]?.body))).toEqual({
        path: "outputs/variant_result.png",
      });
    });
  });

  it("renders drag handle and activates draggable on handle hover", () => {
    const onDragStart = vi.fn();
    const { container } = render(
      <CompareWorkspaceProvider>
        <VariantCard
          canDelete={true}
          index={1}
          isBusy={false}
          isSelectedForCompare={false}
          onDragStart={onDragStart}
          onRun={vi.fn()}
          onToggleCompare={vi.fn()}
          roundId="round-1"
          template={template}
          variant={variantWithImage}
        />
      </CompareWorkspaceProvider>,
    );

    const handle = screen.getByLabelText("拖拽调整变体顺序");
    expect(handle).toBeTruthy();

    const article = container.querySelector("article.variant-card") as HTMLElement;
    expect(article).toBeTruthy();
    expect(article.getAttribute("draggable")).toBe("false");

    fireEvent.mouseEnter(handle);
    expect(article.getAttribute("draggable")).toBe("true");

    fireEvent.mouseLeave(handle);
    expect(article.getAttribute("draggable")).toBe("false");

    const resultContainer = container.querySelector(".variant-result-container");
    expect(resultContainer?.classList.contains("has-image")).toBe(true);
  });
});
