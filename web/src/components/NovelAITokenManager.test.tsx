import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as apiClient from "../api/client";
import type { NovelAITokenList, NovelAIUsageInfo } from "../api/types";
import { NovelAITokenManager } from "./NovelAITokenManager";

function tokenList(
  activeId: string,
  extra: Partial<Record<string, string>> = {},
): NovelAITokenList {
  return {
    schema: "tags-machine-core.web.novelai-tokens/v1",
    active_id: activeId,
    tokens: [
      {
        id: "config",
        name: extra.config ?? "配置文件",
        token_masked: "pst-...1111",
        source: "config",
        active: activeId === "config",
      },
      {
        id: "alt",
        name: extra.alt ?? "小号",
        token_masked: "pst-...2222",
        source: "saved",
        active: activeId === "alt",
      },
    ],
  };
}

describe("NovelAITokenManager", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(apiClient, "listNovelAITokens").mockResolvedValue(tokenList("config"));
    vi.spyOn(apiClient, "getNovelAITokenUsage").mockRejectedValue(new Error("offline"));
  });

  afterEach(() => {
    cleanup();
  });

  it("shows subscription tier, Anlas and V5 quota for each token", async () => {
    const usage = {
      configured: true,
      token_masked: "",
      fixed_anlas: 0,
      purchased_anlas: 0,
      time_until_next_percent: 0,
      unlimited_v5_eligible: false,
    };
    const usages: Record<string, NovelAIUsageInfo> = {
      config: {
        ...usage,
        active: true,
        tier: 3,
        tier_name: "Opus",
        anlas: 2157,
        usage_percent: 35.4,
      },
      alt: {
        ...usage,
        active: false,
        tier: 0,
        tier_name: "None",
        anlas: 0,
        usage_percent: 0,
        error: "Token 无效或已过期 (HTTP 401)",
      },
    };
    const usageSpy = vi
      .spyOn(apiClient, "getNovelAITokenUsage")
      .mockImplementation(async (id: string) => usages[id]);

    render(<NovelAITokenManager />);

    expect(await screen.findByText("Opus")).toBeDefined();
    expect(screen.getByText("2,157 点")).toBeDefined();
    expect(screen.getByText("V5 35%")).toBeDefined();
    const invalid = screen.getByText("失效");
    expect(invalid.getAttribute("title")).toContain("HTTP 401");
    expect(usageSpy).toHaveBeenCalledWith("config", false);
    expect(usageSpy).toHaveBeenCalledWith("alt", false);

    fireEvent.click(screen.getByRole("button", { name: "刷新全部 token 的订阅和点数" }));
    await waitFor(() => expect(usageSpy).toHaveBeenCalledWith("alt", true));
  });

  it("lists tokens and switches the active one", async () => {
    const onActiveChange = vi.fn();
    const activate = vi
      .spyOn(apiClient, "activateNovelAIToken")
      .mockResolvedValue(tokenList("alt"));

    render(<NovelAITokenManager onActiveChange={onActiveChange} />);

    expect(await screen.findByText("小号")).toBeDefined();
    expect(screen.getByText("pst-...2222")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "切换到 小号" }));

    await waitFor(() => {
      expect(activate).toHaveBeenCalledWith("alt");
      expect(onActiveChange).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button", { name: "小号（使用中）" })).toBeDefined();
    });
  });

  it("adds a token with a custom name", async () => {
    const onActiveChange = vi.fn();
    const add = vi.spyOn(apiClient, "addNovelAIToken").mockResolvedValue({
      ...tokenList("new"),
      tokens: [
        ...tokenList("new").tokens,
        { id: "new", name: "主力号", token_masked: "pst-...3333", source: "saved", active: true },
      ],
    });

    render(<NovelAITokenManager onActiveChange={onActiveChange} />);
    await screen.findByText("小号");

    fireEvent.click(screen.getByRole("button", { name: /添加/ }));
    fireEvent.change(screen.getByLabelText("新 token 名称"), { target: { value: "主力号" } });
    fireEvent.change(screen.getByLabelText("新 token"), { target: { value: " pst-new-3333 " } });
    fireEvent.click(screen.getByRole("button", { name: /添加并切换/ }));

    await waitFor(() => {
      expect(add).toHaveBeenCalledWith({ name: "主力号", token: "pst-new-3333", activate: true });
      expect(screen.getByText("主力号")).toBeDefined();
      expect(onActiveChange).toHaveBeenCalled();
    });
    expect(screen.queryByLabelText("新 token")).toBeNull();
  });

  it("renames a token with Enter and only saves once", async () => {
    const rename = vi
      .spyOn(apiClient, "renameNovelAIToken")
      .mockResolvedValue(tokenList("config", { alt: "备用" }));

    render(<NovelAITokenManager />);
    await screen.findByText("小号");

    fireEvent.click(screen.getByRole("button", { name: "重命名 小号" }));
    const input = screen.getByLabelText("token 名称");
    fireEvent.change(input, { target: { value: "备用" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);

    await waitFor(() => expect(screen.getByText("备用")).toBeDefined());
    expect(rename).toHaveBeenCalledTimes(1);
    expect(rename).toHaveBeenCalledWith("alt", "备用");
  });

  it("Escape cancels a rename without saving", async () => {
    const rename = vi.spyOn(apiClient, "renameNovelAIToken");

    render(<NovelAITokenManager />);
    await screen.findByText("小号");

    fireEvent.click(screen.getByRole("button", { name: "重命名 小号" }));
    const input = screen.getByLabelText("token 名称");
    fireEvent.change(input, { target: { value: "不要" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);

    expect(rename).not.toHaveBeenCalled();
    expect(screen.getByText("小号")).toBeDefined();
  });

  it("deletes saved tokens after confirmation; config token cannot be deleted", async () => {
    const remove = vi.spyOn(apiClient, "deleteNovelAIToken").mockResolvedValue({
      ...tokenList("config"),
      tokens: tokenList("config").tokens.slice(0, 1),
    });

    render(<NovelAITokenManager />);
    await screen.findByText("小号");

    expect(screen.queryByRole("button", { name: "删除 配置文件" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "删除 小号" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "删除" }));

    await waitFor(() => {
      expect(remove).toHaveBeenCalledWith("alt");
      expect(screen.queryByText("小号")).toBeNull();
    });
  });

  it("batch imports tokens and lists skipped duplicates", async () => {
    const onActiveChange = vi.fn();
    const imported = vi.spyOn(apiClient, "importNovelAITokens").mockResolvedValue({
      ...tokenList("config"),
      tokens: [
        ...tokenList("config").tokens,
        { id: "n1", name: "主力号", token_masked: "pst-...3333", source: "saved", active: false },
      ],
      added: [
        { id: "n1", name: "主力号", token_masked: "pst-...3333", source: "saved", active: false },
      ],
      skipped: [
        { line: 2, reason: "duplicate", message: "已存在（小号）" },
        { line: 3, reason: "duplicate", message: "已存在（主力号）" },
      ],
    });

    render(<NovelAITokenManager onActiveChange={onActiveChange} />);
    await screen.findByText("小号");

    fireEvent.click(screen.getByRole("button", { name: /批量导入/ }));
    const text = "主力号 pst-new-3333\npst-saved-2222\npst-new-3333";
    fireEvent.change(screen.getByLabelText("批量导入 token"), { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: /^导入$/ }));

    await waitFor(() => {
      expect(imported).toHaveBeenCalledWith(text);
      expect(screen.getByText("主力号")).toBeDefined();
    });
    expect(screen.getByRole("status").textContent).toContain("导入 1 个，跳过重复 2 个");
    expect(screen.getByText("第 2 行：已存在（小号）")).toBeDefined();
    expect(screen.queryByLabelText("批量导入 token")).toBeNull();
    // 导入不切换当前 token
    expect(onActiveChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "关闭导入结果" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("imports accounts into the background login queue and polls until logged in", async () => {
    const account = (status: "pending" | "ok" | "failed", error: string | null = null) => ({
      id: "acc1",
      name: "one@example.com",
      kind: "account" as const,
      account: "one@example.com",
      token_masked: "",
      source: "saved" as const,
      active: false,
      login_status: status,
      login_error: error,
    });
    const listSpy = vi.spyOn(apiClient, "listNovelAITokens");
    const importAccounts = vi.spyOn(apiClient, "importNovelAIAccounts").mockResolvedValue({
      ...tokenList("config"),
      tokens: [...tokenList("config").tokens, account("pending")],
      added: [account("pending")],
      requeued: [],
      skipped: [{ line: 9, reason: "duplicate", message: "已存在（two@example.com）" }],
    });
    const importTokens = vi.spyOn(apiClient, "importNovelAITokens");

    render(<NovelAITokenManager />);
    await screen.findByText("小号");

    fireEvent.click(screen.getByRole("button", { name: /批量导入/ }));
    fireEvent.click(screen.getByRole("tab", { name: "账号密码" }));
    const text = 'NAI_ACCOUNT = [{"username": "one@example.com", "password": "pw"}]';
    fireEvent.change(screen.getByLabelText("批量导入账号"), { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: /^导入$/ }));

    await waitFor(() => {
      expect(importAccounts).toHaveBeenCalledWith(text);
      expect(screen.getByText("one@example.com")).toBeDefined();
    });
    expect(importTokens).not.toHaveBeenCalled();
    expect(screen.getByText("账号登录")).toBeDefined();
    expect(screen.getByText(/排队登录/)).toBeDefined();
    expect(screen.getByText(/后台登录 1 个/)).toBeDefined();
    expect(screen.getByRole("status").textContent).toContain(
      "导入 1 个，跳过重复 1 个，正在后台登录",
    );
    // 排队中的账号不查用量
    expect(apiClient.getNovelAITokenUsage).not.toHaveBeenCalledWith("acc1", false);

    // 后台登录完成后，轮询刷新列表，排队标记消失并开始查用量
    listSpy.mockResolvedValue({
      ...tokenList("config"),
      tokens: [...tokenList("config").tokens, account("ok")],
    });
    await waitFor(
      () => {
        expect(screen.queryByText(/排队登录/)).toBeNull();
        expect(apiClient.getNovelAITokenUsage).toHaveBeenCalledWith("acc1", false);
      },
      { timeout: 5000 },
    );
  });

  it("shows failed account login and puts it back in the queue", async () => {
    const failed = {
      id: "acc1",
      name: "bad@example.com",
      kind: "account" as const,
      account: "bad@example.com",
      token_masked: "",
      source: "saved" as const,
      active: false,
      login_status: "failed" as const,
      login_error: "账号或密码错误 (HTTP 401)",
    };
    vi.spyOn(apiClient, "listNovelAITokens").mockResolvedValue({
      ...tokenList("config"),
      tokens: [...tokenList("config").tokens, failed],
    });
    const relogin = vi.spyOn(apiClient, "reloginNovelAIAccount").mockResolvedValue({
      ...tokenList("config"),
      tokens: [
        ...tokenList("config").tokens,
        { ...failed, login_status: "pending", login_error: null },
      ],
    });

    render(<NovelAITokenManager />);

    expect(await screen.findByText("登录失败")).toBeDefined();
    expect(screen.getByText("账号或密码错误 (HTTP 401)")).toBeDefined();
    expect(apiClient.getNovelAITokenUsage).not.toHaveBeenCalledWith("acc1", false);

    fireEvent.click(screen.getByRole("button", { name: "重新登录 bad@example.com" }));

    await waitFor(() => {
      expect(relogin).toHaveBeenCalledWith("acc1");
      expect(screen.getByText(/排队登录/)).toBeDefined();
    });
  });

  it("does not submit an empty import", async () => {
    const imported = vi.spyOn(apiClient, "importNovelAITokens");

    render(<NovelAITokenManager />);
    await screen.findByText("小号");

    fireEvent.click(screen.getByRole("button", { name: /批量导入/ }));
    fireEvent.click(screen.getByRole("button", { name: /^导入$/ }));

    expect(imported).not.toHaveBeenCalled();
    expect(screen.getByText(/每行一个/, { selector: ".popover-alert" })).toBeDefined();
  });

  it("shows API errors", async () => {
    vi.spyOn(apiClient, "addNovelAIToken").mockRejectedValue(new Error("这个 token 已经添加过了"));

    render(<NovelAITokenManager />);
    await screen.findByText("小号");

    fireEvent.click(screen.getByRole("button", { name: /添加/ }));
    fireEvent.change(screen.getByLabelText("新 token"), { target: { value: "pst-dup" } });
    fireEvent.click(screen.getByRole("button", { name: /添加并切换/ }));

    expect(await screen.findByText(/已经添加过了/)).toBeDefined();
    expect(screen.getByLabelText("新 token")).toBeDefined();
  });
});
