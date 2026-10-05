import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { groupTitle, HistoryPage } from "./HistoryPage";

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const runs = [
  {
    id: "compares/sequential_20261005053038_a17a04ff",
    name: "sequential_20261005053038_a17a04ff",
    kind: "sequential",
    path: "F:/outputs/compares/sequential_20261005053038_a17a04ff",
    created_at: 1_790_000_200,
    image_count: 2,
    group_count: 2,
    covers: ["F:/outputs/compares/s/group_001_seed_1/a.png"],
    job: { id: "bg-1", label: "Sequential · 2 个动作", status: "succeeded" },
  },
  {
    id: "loose/2026-10-05",
    name: "散图 · 2026-10-05",
    kind: "loose",
    path: "F:/outputs",
    created_at: 1_790_000_100,
    image_count: 1,
    group_count: 1,
    covers: ["F:/outputs/x.png"],
    job: null,
  },
];

function image(path: string, group: string, action: string, seed: number, backend = "comfyui") {
  return {
    path,
    filename: path.split("/").pop(),
    group,
    created_at: 1_790_000_150,
    size_bytes: 1000,
    info: {
      backend,
      seed,
      width: 1024,
      height: 1536,
      nodes: [{ role: "artist", name: "p4" }, { role: "character", name: "homura" }, { role: "action", name: action }],
      timing: { execution_seconds: 38.7 },
    },
  };
}

describe("HistoryPage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("lists runs newest first and shows the selected run's images grouped with varying nodes first", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/history/runs")) return response({ runs });
      if (url.includes("/history/images")) {
        const runId = new URL(url).searchParams.get("run_id");
        const images = runId === runs[0].id
          ? [
            image("F:/o/group_001_seed_1/a.png", "group_001_seed_1", "standing", 1),
            image("F:/o/group_002_seed_2/b.png", "group_002_seed_2", "sitting", 2, "novelai"),
          ]
          : [image("F:/outputs/x.png", "", "lying", 3)];
        return response({ run_id: runId, path: "F:/o", total: images.length, offset: 0, limit: 300, images });
      }
      if (url.includes("/results/image-metadata")) return response({ path: "", filename: "a.png", size_bytes: 1, modified_at: "", model: null, dimensions: null, png_text: {}, parameters: {} });
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<HistoryPage />);

    const runButtons = await screen.findAllByRole("button", { name: /Sequential · 2 个动作|散图 · 2026-10-05/ });
    expect(runButtons.map((button) => button.textContent?.includes("Sequential · 2 个动作"))).toEqual([true, false]);
    expect(await screen.findByText("Group 1 · Seed 1")).toBeTruthy();
    expect(screen.getByText("Group 2 · Seed 2")).toBeTruthy();
    // 动作在变，排在角色前面；画风不变时不显示。
    expect(screen.getByRole("img", { name: "standing · homura" })).toBeTruthy();
    expect(screen.getAllByText("38.7 秒")).toHaveLength(2);

    fireEvent.change(screen.getByLabelText("筛选图片"), { target: { value: "sitting" } });
    expect(screen.queryByRole("img", { name: "standing · homura" })).toBeNull();
    expect(screen.getByText("1 / 2 张")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("筛选图片"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("按后端筛选"), { target: { value: "novelai" } });
    expect(screen.getByText("1 / 2 张")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "打开 b.png 大图" }));
    expect(await screen.findByRole("dialog", { name: "图片详情" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "关闭图片详情" }));

    fireEvent.click(screen.getByRole("button", { name: "散图" }));
    fireEvent.click(await screen.findByRole("button", { name: /散图 · 2026-10-05/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("run_id=loose%2F2026-10-05"))).toBe(true));
    expect(localStorage.getItem("promptatelier.history-run/v1")).toBe("loose/2026-10-05");
  });

  it("formats group directory names", () => {
    expect(groupTitle("group_003_seed_42")).toBe("Group 3 · Seed 42");
    expect(groupTitle("misc")).toBe("misc");
  });
});
