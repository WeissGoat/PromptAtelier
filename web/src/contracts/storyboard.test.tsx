import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { boardArtists, ContractStoryboard, DEFAULT_BOARD_FILTERS, filterBoardImages, groupRounds, roundCount } from "./ContractStoryboard";
import type { ContractDetail, ContractResultImage, ContractResults } from "./types";

function image(patch: Partial<ContractResultImage>): ContractResultImage {
  return {
    path: "outputs/x.png",
    run: "contract_1",
    frame_id: "f01",
    artist: "A",
    seed: 1,
    created_at: 100,
    current: true,
    picked: false,
    ...patch,
  };
}

const images = [
  image({ path: "a1.png", run: "contract_2", artist: "A", created_at: 300, seed: 11 }),
  image({ path: "b1.png", run: "contract_2", artist: "B", created_at: 290, seed: 12, picked: true }),
  image({ path: "a0.png", run: "contract_1", artist: "A", created_at: 100, seed: 13, current: false }),
  image({ path: "a2.png", run: "contract_2", artist: "A", created_at: 280, seed: 14 }),
];

describe("storyboard helpers", () => {
  it("groups by run and artist, newest round first", () => {
    const rounds = groupRounds(images);
    expect(rounds.map((round) => round.key)).toEqual(["contract_2|A", "contract_2|B", "contract_1|A"]);
    expect(rounds[0].images.map((item) => item.path)).toEqual(["a1.png", "a2.png"]);
    expect(rounds[0].startedAt).toBe(280);
    expect(roundCount(images)).toBe(3);
  });

  it("filters by artist, current prompt and picks", () => {
    expect(filterBoardImages(images, { ...DEFAULT_BOARD_FILTERS, artist: "A" }).map((item) => item.path)).toEqual(["a1.png", "a0.png", "a2.png"]);
    expect(filterBoardImages(images, { ...DEFAULT_BOARD_FILTERS, currentOnly: true })).toHaveLength(3);
    expect(filterBoardImages(images, { ...DEFAULT_BOARD_FILTERS, pickedOnly: true }).map((item) => item.path)).toEqual(["b1.png"]);
  });

  it("lists artists by image count", () => {
    const results = { id: "c", frames: { f01: images, f02: [image({ path: "b2.png", frame_id: "f02", artist: "B" })] }, picks: {} } as ContractResults;
    expect(boardArtists(results)).toEqual([{ name: "A", count: 3 }, { name: "B", count: 2 }]);
  });
});

function frame(id: string, title: string) {
  return {
    id,
    title,
    source: null,
    member_index: null,
    is_custom: true,
    inspired_by: [],
    characters: [],
    size: null,
    prompts: { positive: `${title} prompt`, negative: "" },
    submit: { positive: `${title} prompt`, negative: "" },
  };
}

describe("ContractStoryboard", () => {
  afterEach(cleanup);
  const detail = {
    id: "c",
    request: { title: "测试契约" },
    frames: [frame("f01", "起手"), frame("f02", "收尾")],
    sources: { characters: {}, references: {}, action_group: null },
  } as unknown as ContractDetail;
  const results = { id: "c", frames: { f01: images }, picks: {} } as ContractResults;

  function renderBoard(overrides: Partial<Parameters<typeof ContractStoryboard>[0]> = {}) {
    const props = {
      detail,
      results,
      filters: DEFAULT_BOARD_FILTERS,
      tileSize: "s" as const,
      focusFrame: null,
      onFiltersChange: vi.fn(),
      onTileSizeChange: vi.fn(),
      onFocusHandled: vi.fn(),
      onBack: vi.fn(),
      onGenerate: vi.fn(),
      onOpenImage: vi.fn(),
      onTogglePick: vi.fn(),
      ...overrides,
    };
    render(<ContractStoryboard {...props} />);
    return props;
  }

  it("shows one row per frame with rounds, and generate for frames without images", () => {
    const props = renderBoard();
    const first = document.getElementById("board-f01")!;
    expect(within(first).getAllByText(/张$/).length).toBeGreaterThan(0);
    expect(first.querySelectorAll(".ct-round")).toHaveLength(3);
    expect(first.querySelectorAll(".ct-result.is-old")).toHaveLength(1);
    const second = document.getElementById("board-f02")!;
    expect(within(second).getByText("还没有出图。")).toBeTruthy();
    fireEvent.click(within(second).getByRole("button", { name: /生成此帧/ }));
    expect(props.onGenerate).toHaveBeenCalledWith("f02");
  });

  it("opens the viewer over the filtered images of the frame", () => {
    const props = renderBoard({ filters: { ...DEFAULT_BOARD_FILTERS, artist: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "查看 f01 A seed 14" }));
    const [openedFrame, opened, index] = props.onOpenImage.mock.calls[0];
    expect(openedFrame.id).toBe("f01");
    expect(opened.map((item: ContractResultImage) => item.path)).toEqual(["a1.png", "a0.png", "a2.png"]);
    expect(index).toBe(2);
  });

  it("ignores a remembered artist that this contract does not have", () => {
    renderBoard({ filters: { ...DEFAULT_BOARD_FILTERS, artist: "Z" } });
    expect((screen.getByLabelText("按画风筛选") as HTMLSelectElement).value).toBe("");
    expect(document.getElementById("board-f01")!.querySelectorAll(".ct-result")).toHaveLength(4);
  });
});
