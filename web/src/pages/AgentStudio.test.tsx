import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { contractsApi } from "../contracts/api";
import { draftFromContract, EMPTY_DRAFT } from "../contracts/ContractRequestPanel";
import { STORAGE_KEYS } from "../contracts/persist";
import type { ContractDetail, ContractSources, FormatSummary } from "../contracts/types";
import { AgentStudio } from "./AgentStudio";

vi.mock("../components/GenerationTasksPanel", () => ({ GenerationTasksPanel: () => null }));
vi.mock("../contracts/ContractGeneratePanel", async (importOriginal) => ({
  ...await importOriginal<typeof import("../contracts/ContractGeneratePanel")>(),
  ContractGeneratePanel: () => null,
}));

function contract(id = "a"): ContractDetail {
  return {
    id,
    file: { path: `contracts/${id}.md`, hash: id, mtime: 1 },
    summary: {
      id, title: `历史 ${id}`, status: "pending", frame_count: 0, mtime: 1,
      target_format: "nai-v4", nodes: { characters: { c1: "series/one" }, action_group: "st_1" },
    },
    request: {
      schema: "v1", id, title: `历史 ${id}`, status: "pending", created_at: "", author: "",
      target_format: "nai-v4", requirements: `要求 ${id}`,
      nodes: {
        characters: { c2: { ref: "series/two" }, c1: { ref: "series/one" } },
        action_group: { ref: "st_1" }, clothing: { ref: "uniform" }, background: { ref: "classroom" },
      },
      options: { keep_order: false, allow_new_frames: false, max_new_frames: 0 },
    },
    sources: {
      characters: {
        c1: { path: "F:/角色/series/one", name: "角色一" },
        c2: { path: "F:/角色/series/two", name: "角色二" },
      },
      action_group: { path: "F:/动作改2/st_1", name: "st_1" },
      clothing: { path: "F:/服装/uniform", name: "校服" },
      background: { path: "F:/背景/classroom", name: "教室" },
      references: {},
    } as unknown as ContractSources,
    preamble: "", frames: [], stale: [], coverage: null, issues: [],
    issue_counts: { error: 0, warn: 0, info: 0 },
    profile: { id: "nai-v4", label: "NAI V4" } as FormatSummary,
  };
}

function requestPanel() {
  return within(screen.getByRole("region", { name: "请求与历史" }));
}

function selectHistory(id: string) {
  fireEvent.click(requestPanel().getByRole("button", { name: new RegExp(`历史 ${id}`) }));
}

function savedDraft() {
  return JSON.parse(localStorage.getItem(STORAGE_KEYS.draft)!);
}

describe("AgentStudio history request reuse", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.spyOn(contractsApi, "formats").mockResolvedValue([
      { id: "nai-v4", label: "NAI V4" }, { id: "nai-v4.5", label: "NAI V4.5" },
    ] as FormatSummary[]);
    vi.spyOn(contractsApi, "list").mockResolvedValue({ contracts: [contract().summary], now: 1 });
    vi.spyOn(contractsApi, "get").mockResolvedValue(contract());
    vi.spyOn(contractsApi, "results").mockImplementation(async (id) => ({ id, frames: {}, picks: {} }));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows the full plan separately from the original requirements", async () => {
    const detail = contract();
    detail.preamble = "### 阶段安排\n1. 保持戒备\n2. 逐渐放松\n\n### 状态变化规划\n背景按镜头裁剪。";
    vi.mocked(contractsApi.get).mockResolvedValue(detail);
    render(<AgentStudio />);
    await screen.findByText("历史 a", { selector: "strong" });
    selectHistory("a");
    const summary = await screen.findByText("计划区", { selector: "summary" });
    expect(summary.closest("details")?.querySelector("pre")?.textContent).toBe(detail.preamble);
    expect(screen.getByText("要求 a", { selector: "blockquote" })).toBeTruthy();
  });

  it("fills the full request, restores it on reselect, and creates with the edited request", async () => {
    const original = contract();
    vi.spyOn(contractsApi, "create").mockResolvedValue({ ...original, id: "new" });
    vi.spyOn(contractsApi, "prompt").mockResolvedValue("agent prompt");
    render(<AgentStudio />);
    await screen.findByText("历史 a", { selector: "strong" });
    selectHistory("a");

    await waitFor(() => expect(savedDraft().requirements).toBe("要求 a"));
    const panel = requestPanel();
    expect(panel.getAllByText(/角色[一二]/).map((node) => node.textContent)).toEqual(["角色一", "角色二"]);
    expect((panel.getByLabelText("服装（可选）") as HTMLInputElement).value).toBe("校服");
    expect((panel.getByLabelText("背景（可选）") as HTMLInputElement).value).toBe("教室");
    expect((panel.getByLabelText("目标格式") as HTMLSelectElement).value).toBe("nai-v4");
    expect((panel.getByLabelText("保持顺序") as HTMLInputElement).checked).toBe(false);
    expect((panel.getByLabelText("允许新增帧") as HTMLInputElement).checked).toBe(false);
    expect((panel.getByLabelText("最多新增") as HTMLInputElement).value).toBe("0");

    fireEvent.change(panel.getByLabelText("定制要求"), { target: { value: "临时修改" } });
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(contractsApi.get).toHaveBeenCalledTimes(2));
    expect((panel.getByLabelText("定制要求") as HTMLTextAreaElement).value).toBe("临时修改");
    selectHistory("a");
    await waitFor(() => expect(savedDraft().requirements).toBe("要求 a"));

    fireEvent.change(panel.getByLabelText("定制要求"), { target: { value: "新要求" } });
    fireEvent.click(panel.getByRole("button", { name: "新建并生成要求" }));
    await waitFor(() => expect(contractsApi.create).toHaveBeenCalledWith({
      action_group: "F:/动作改2/st_1",
      characters: ["F:/角色/series/one", "F:/角色/series/two"],
      clothing: "F:/服装/uniform", background: "F:/背景/classroom",
      requirements: "新要求", target_format: "nai-v4",
      options: { keep_order: false, allow_new_frames: false, max_new_frames: 0 },
    }));
    await screen.findByRole("dialog", { name: "要求 prompt" });
  });

  it("preserves the saved draft on page load and clears absent optional nodes on explicit selection", async () => {
    const previous = { ...draftFromContract(contract()), requirements: "未提交草稿" };
    localStorage.setItem(STORAGE_KEYS.draft, JSON.stringify(previous));
    localStorage.setItem("promptatelier.agent-studio.active/v1", "a");
    const historical = contract();
    historical.request.nodes.clothing = null;
    historical.request.nodes.background = null;
    historical.sources.clothing = null;
    historical.sources.background = null;
    vi.mocked(contractsApi.get).mockResolvedValue(historical);
    render(<AgentStudio />);

    await screen.findByRole("heading", { name: "历史 a" });
    await screen.findByText("历史 a", { selector: "strong" });
    expect(savedDraft().requirements).toBe("未提交草稿");
    selectHistory("a");
    await waitFor(() => expect(savedDraft().requirements).toBe("要求 a"));
    expect(savedDraft().clothing).toBeNull();
    expect(savedDraft().background).toBeNull();
  });

  it("keeps the last selected contract when detail requests finish out of order", async () => {
    let resolveFirst!: (value: ContractDetail) => void;
    const first = new Promise<ContractDetail>((resolve) => { resolveFirst = resolve; });
    vi.mocked(contractsApi.list).mockResolvedValue({ contracts: [contract("a").summary, contract("b").summary], now: 1 });
    vi.mocked(contractsApi.get).mockImplementation((id) => id === "a" ? first : Promise.resolve(contract("b")));
    render(<AgentStudio />);
    await screen.findByText("历史 b", { selector: "strong" });
    selectHistory("a");
    selectHistory("b");
    await waitFor(() => expect(savedDraft().requirements).toBe("要求 b"));
    await act(async () => { resolveFirst(contract("a")); });
    expect(savedDraft().requirements).toBe("要求 b");
    expect(screen.getByRole("heading", { name: "历史 b" })).toBeTruthy();
  });

  it("preserves the draft when a contract cannot be parsed and retains unresolved node references", async () => {
    vi.mocked(contractsApi.get).mockResolvedValue({ id: "a", parse_error: "YAML 格式错误", text: "broken" } as ContractDetail);
    localStorage.setItem(STORAGE_KEYS.draft, JSON.stringify({ ...EMPTY_DRAFT, requirements: "保留草稿" }));
    render(<AgentStudio />);
    await screen.findByText("历史 a", { selector: "strong" });
    selectHistory("a");
    await screen.findByText("契约文件无法解析：YAML 格式错误");
    expect(savedDraft().requirements).toBe("保留草稿");

    const missing = contract();
    missing.sources.characters = {};
    missing.sources.action_group = null;
    const recovered = draftFromContract(missing);
    expect(recovered.characters).toEqual([{ ref: "series/one", name: "one" }, { ref: "series/two", name: "two" }]);
    expect(recovered.actionGroup).toEqual({ ref: "st_1", name: "st_1" });
  });
});
