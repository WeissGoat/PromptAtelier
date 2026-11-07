import {
  Check,
  FileUp,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  activateNovelAIToken,
  addNovelAIToken,
  deleteNovelAIToken,
  errorMessage,
  getNovelAITokenUsage,
  importNovelAIAccounts,
  importNovelAITokens,
  listNovelAITokens,
  reloginNovelAIAccount,
  renameNovelAIToken,
} from "../api/client";
import type {
  NovelAITokenEntry,
  NovelAITokenImportResult,
  NovelAITokenList,
  NovelAIUsageInfo,
} from "../api/types";

type Props = {
  /** 当前生效的 token 变了（切换、添加、删除），外面重新查用量。 */
  onActiveChange?: () => void;
};

export function NovelAITokenManager({ onActiveChange }: Props) {
  const [list, setList] = useState<NovelAITokenList | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [mode, setMode] = useState<"list" | "add" | "import">("list");
  const adding = mode === "add";
  const [importText, setImportText] = useState("");
  // 批量导入的内容：token（pst-…）或账号密码（旧 NAI_ACCOUNT）
  const [importKind, setImportKind] = useState<"tokens" | "accounts">("tokens");
  const [importSummary, setImportSummary] = useState<NovelAITokenImportResult | null>(null);
  const [newName, setNewName] = useState("");
  const [newToken, setNewToken] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  // 回车保存或 Esc 取消后输入框卸载时可能再触发一次 blur，用 ref 记住是否还在编辑
  const editingRef = useRef<string | null>(null);
  const [usages, setUsages] = useState<Record<string, NovelAIUsageInfo>>({});
  const [usageLoading, setUsageLoading] = useState(false);
  const usageSeq = useRef(0);

  useEffect(() => {
    let unmounted = false;
    listNovelAITokens()
      .then((res) => {
        if (!unmounted) setList(res);
      })
      .catch((err) => {
        if (!unmounted) setError(errorMessage(err));
      });
    return () => {
      unmounted = true;
    };
  }, []);

  // token 列表变了（首次读取、添加、导入、删除、账号登录完成）就查一遍各自的订阅和点数；后端按 token 缓存 60s。
  // 每个 token 单独请求、最多同时 USAGE_CONCURRENCY 个，查完一个显示一个，不用等全部返回。
  // 还在排队或登录失败的账号不查（查了也只会报错），等后台登录好了再查。
  const tokenIdsKey = (list?.tokens ?? [])
    .filter((entry) => !accountWaiting(entry))
    .map((entry) => entry.id)
    .join(",");
  const pendingCount = (list?.tokens ?? []).filter(
    (entry) => entry.kind === "account" && entry.login_status === "pending",
  ).length;

  // 后台登录队列没跑完时定时刷新列表，看到每个账号登录成功或失败
  useEffect(() => {
    if (!pendingCount) return;
    const timer = window.setInterval(() => {
      listNovelAITokens()
        .then(setList)
        .catch(() => {
          // 刷新失败就等下一次
        });
    }, LOGIN_POLL_MS);
    return () => window.clearInterval(timer);
  }, [pendingCount]);

  const loadUsages = useCallback(async (ids: string[], refresh: boolean) => {
    const seq = ++usageSeq.current;
    setUsageLoading(true);
    let next = 0;
    async function worker() {
      while (next < ids.length && seq === usageSeq.current) {
        const id = ids[next++];
        try {
          const info = await getNovelAITokenUsage(id, refresh);
          if (seq === usageSeq.current) setUsages((prev) => ({ ...prev, [id]: info }));
        } catch {
          // 用量只是辅助信息，查失败时保持原样，不挡住 token 管理
        }
      }
    }
    await Promise.all(
      Array.from({ length: Math.min(USAGE_CONCURRENCY, ids.length) }, () => worker()),
    );
    if (seq === usageSeq.current) setUsageLoading(false);
  }, []);

  useEffect(() => {
    if (!tokenIdsKey) return;
    void loadUsages(tokenIdsKey.split(","), false);
  }, [tokenIdsKey, loadUsages]);

  useEffect(
    () => () => {
      usageSeq.current += 1;
    },
    [],
  );

  async function run(id: string, action: () => Promise<NovelAITokenList>): Promise<boolean> {
    setBusyId(id);
    setError("");
    const previousActive = list?.active_id ?? null;
    try {
      const next = await action();
      setList(next);
      if (next.active_id !== previousActive) onActiveChange?.();
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setBusyId(null);
    }
  }

  async function submitAdd(event: React.FormEvent) {
    event.preventDefault();
    if (!newToken.trim()) {
      setError("请粘贴 NovelAI token");
      return;
    }
    const ok = await run("__add__", () =>
      addNovelAIToken({
        name: newName.trim(),
        token: newToken.trim(),
        activate: true,
      }),
    );
    if (ok) {
      setMode("list");
      setNewName("");
      setNewToken("");
    }
  }

  async function submitImport(event: React.FormEvent) {
    event.preventDefault();
    if (!importText.trim()) {
      setError(
        importKind === "accounts" ? "请粘贴账号，每行「邮箱 密码」" : "请粘贴 token，每行一个",
      );
      return;
    }
    let result: NovelAITokenImportResult | null = null;
    const ok = await run("__import__", async () => {
      result =
        importKind === "accounts"
          ? await importNovelAIAccounts(importText)
          : await importNovelAITokens(importText);
      return result;
    });
    if (ok && result) {
      setImportSummary(result);
      setMode("list");
      setImportText("");
    }
  }

  function openMode(next: "add" | "import") {
    setMode(next);
    setError("");
    setImportSummary(null);
  }

  function closeForm() {
    setMode("list");
    setNewName("");
    setNewToken("");
    setImportText("");
    setError("");
  }

  function stopRename() {
    editingRef.current = null;
    setEditingId(null);
  }

  async function submitRename(entry: NovelAITokenEntry) {
    if (editingRef.current !== entry.id) return;
    const name = editName.trim();
    if (!name || name === entry.name) {
      stopRename();
      return;
    }
    editingRef.current = null;
    const ok = await run(entry.id, () => renameNovelAIToken(entry.id, name));
    if (ok) setEditingId(null);
    else editingRef.current = entry.id;
  }

  function startRename(entry: NovelAITokenEntry) {
    setConfirmDeleteId(null);
    editingRef.current = entry.id;
    setEditingId(entry.id);
    setEditName(entry.name);
  }

  const tokens = list?.tokens ?? [];

  return (
    <div className="novelai-token-manager">
      <div className="token-manager-header">
        <span className="label">
          <KeyRound size={12} /> 账号 Token{tokens.length ? ` (${tokens.length})` : ""}
          {tokens.length ? (
            <button
              aria-label="刷新全部 token 的订阅和点数"
              className="token-icon token-usage-refresh"
              disabled={usageLoading}
              onClick={() =>
                void loadUsages(
                  tokens.filter((entry) => !accountWaiting(entry)).map((entry) => entry.id),
                  true,
                )
              }
              title="刷新全部 token 的订阅和点数"
              type="button"
            >
              <RefreshCw className={usageLoading ? "spin" : ""} size={11} />
            </button>
          ) : null}
          {pendingCount ? (
            <span
              className="token-queue-note"
              title="账号在后台一个接一个登录，被限流会自动等待重试"
            >
              <Loader2 className="spin" size={10} /> 后台登录 {pendingCount} 个
            </span>
          ) : null}
        </span>
        {mode === "list" ? (
          <span className="token-header-actions">
            <button className="token-add-toggle" onClick={() => openMode("add")} type="button">
              <Plus size={12} /> 添加
            </button>
            <button className="token-add-toggle" onClick={() => openMode("import")} type="button">
              <FileUp size={12} /> 批量导入
            </button>
          </span>
        ) : null}
      </div>

      {error ? <div className="popover-alert error">{error}</div> : null}
      {importSummary ? (
        <ImportSummary result={importSummary} onClose={() => setImportSummary(null)} />
      ) : null}

      {list === null && !error ? (
        <div className="token-empty">
          <Loader2 className="spin" size={12} /> 读取中…
        </div>
      ) : null}
      {list !== null && tokens.length === 0 && mode === "list" ? (
        <div className="token-empty">还没有 token，点「添加」粘贴一个。</div>
      ) : null}

      {tokens.length > 0 ? (
        <ul className="token-list">
          {tokens.map((entry) => {
            const busy = busyId === entry.id;
            const editing = editingId === entry.id;
            const confirming = confirmDeleteId === entry.id;
            return (
              <li className={entry.active ? "token-row active" : "token-row"} key={entry.id}>
                <button
                  aria-label={entry.active ? `${entry.name}（使用中）` : `切换到 ${entry.name}`}
                  aria-pressed={entry.active}
                  className="token-select"
                  disabled={busyId !== null || entry.active}
                  onClick={() => run(entry.id, () => activateNovelAIToken(entry.id))}
                  title={entry.active ? "出图正在用这个 token" : "切换到这个 token"}
                  type="button"
                >
                  {busy && !editing ? (
                    <Loader2 className="spin" size={12} />
                  ) : entry.active ? (
                    <Check size={12} />
                  ) : null}
                </button>

                <div className="token-main">
                  {editing ? (
                    <input
                      aria-label="token 名称"
                      autoFocus
                      className="token-name-input"
                      maxLength={40}
                      onBlur={() => submitRename(entry)}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          void submitRename(entry);
                        } else if (e.key === "Escape") {
                          e.preventDefault();
                          stopRename();
                        }
                      }}
                      value={editName}
                    />
                  ) : (
                    <span className="token-name-line">
                      <span className="token-name" title={entry.name}>
                        {entry.name}
                      </span>
                      {accountWaiting(entry) ? (
                        <LoginStatusTag entry={entry} />
                      ) : (
                        <TierTag info={usages[entry.id]} loading={usageLoading} />
                      )}
                    </span>
                  )}
                  <span className="token-meta">
                    {entry.kind === "account" ? (
                      <>
                        <span className="token-source">账号登录</span>
                        {entry.account && entry.account !== entry.name ? (
                          <span className="font-mono">{entry.account}</span>
                        ) : null}
                      </>
                    ) : entry.token_masked && entry.name !== `Token ${entry.token_masked}` ? (
                      <span className="font-mono">{entry.token_masked}</span>
                    ) : null}
                    {entry.source === "config" ? (
                      <span className="token-source">配置文件</span>
                    ) : null}
                    {accountWaiting(entry) ? (
                      entry.login_error ? (
                        <span
                          className={
                            entry.login_status === "failed"
                              ? "token-login-error"
                              : "token-login-wait"
                          }
                          title={entry.login_error}
                        >
                          {entry.login_error}
                        </span>
                      ) : null
                    ) : (
                      <UsageMeta info={usages[entry.id]} />
                    )}
                  </span>
                </div>

                <div className="token-actions">
                  {confirming ? (
                    <>
                      <button
                        className="token-icon danger"
                        disabled={busyId !== null}
                        onClick={async () => {
                          const ok = await run(entry.id, () => deleteNovelAIToken(entry.id));
                          if (ok) setConfirmDeleteId(null);
                        }}
                        title="确认删除"
                        type="button"
                      >
                        删除
                      </button>
                      <button
                        aria-label="取消删除"
                        className="token-icon"
                        onClick={() => setConfirmDeleteId(null)}
                        title="取消"
                        type="button"
                      >
                        <X size={12} />
                      </button>
                    </>
                  ) : (
                    <>
                      {entry.kind === "account" && entry.login_status === "failed" ? (
                        <button
                          aria-label={`重新登录 ${entry.name}`}
                          className="token-icon"
                          disabled={busyId !== null}
                          onClick={() => run(entry.id, () => reloginNovelAIAccount(entry.id))}
                          title="放回后台重新登录"
                          type="button"
                        >
                          <RotateCcw size={12} />
                        </button>
                      ) : null}
                      <button
                        aria-label={`重命名 ${entry.name}`}
                        className="token-icon"
                        disabled={busyId !== null}
                        onClick={() => startRename(entry)}
                        title="重命名"
                        type="button"
                      >
                        <Pencil size={12} />
                      </button>
                      {entry.source === "saved" ? (
                        <button
                          aria-label={`删除 ${entry.name}`}
                          className="token-icon"
                          disabled={busyId !== null}
                          onClick={() => {
                            stopRename();
                            setConfirmDeleteId(entry.id);
                          }}
                          title="删除"
                          type="button"
                        >
                          <Trash2 size={12} />
                        </button>
                      ) : null}
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}

      {adding ? (
        <form className="token-add-form" onSubmit={submitAdd}>
          <input
            aria-label="新 token 名称"
            maxLength={40}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="名称（可选，如：主力号）"
            value={newName}
          />
          <input
            aria-label="新 token"
            autoComplete="off"
            autoFocus
            onChange={(e) => setNewToken(e.target.value)}
            placeholder="粘贴 pst-… 开头的 Persistent API Token"
            spellCheck={false}
            type="password"
            value={newToken}
          />
          <div className="token-add-buttons">
            <button className="token-icon" onClick={closeForm} type="button">
              取消
            </button>
            <button className="refresh-button" disabled={busyId !== null} type="submit">
              {busyId === "__add__" ? <Loader2 className="spin" size={12} /> : <Plus size={12} />}
              添加并切换
            </button>
          </div>
        </form>
      ) : null}

      {mode === "import" ? (
        <form className="token-add-form" onSubmit={submitImport}>
          <div className="token-import-kind" role="tablist">
            <button
              aria-selected={importKind === "tokens"}
              className={importKind === "tokens" ? "active" : ""}
              onClick={() => setImportKind("tokens")}
              role="tab"
              type="button"
            >
              Token
            </button>
            <button
              aria-selected={importKind === "accounts"}
              className={importKind === "accounts" ? "active" : ""}
              onClick={() => setImportKind("accounts")}
              role="tab"
              type="button"
            >
              账号密码
            </button>
          </div>
          <textarea
            aria-label={importKind === "accounts" ? "批量导入账号" : "批量导入 token"}
            autoComplete="off"
            autoFocus
            className="token-import-input"
            onChange={(e) => setImportText(e.target.value)}
            placeholder={
              importKind === "accounts" ? ACCOUNT_IMPORT_PLACEHOLDER : IMPORT_PLACEHOLDER
            }
            rows={5}
            spellCheck={false}
            value={importText}
          />
          <span className="token-import-hint">
            {importKind === "accounts"
              ? "导入后在后台一个接一个登录，被限流会自动等待重试；已登录的账号跳过，登录失败过的重新排队。"
              : "已存在的和重复的会自动跳过，导入后不会切换当前 token。"}
          </span>
          <div className="token-add-buttons">
            <button className="token-icon" onClick={closeForm} type="button">
              取消
            </button>
            <button className="refresh-button" disabled={busyId !== null} type="submit">
              {busyId === "__import__" ? (
                <Loader2 className="spin" size={12} />
              ) : (
                <FileUp size={12} />
              )}
              导入
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

const USAGE_CONCURRENCY = 4;
// 有账号在后台排队登录时，多久刷新一次列表
const LOGIN_POLL_MS = 3000;

const IMPORT_PLACEHOLDER = [
  "每行一个 token，可在前面写名称：",
  "pst-aaaa…",
  "主力号 pst-bbbb…",
  "# 开头的行忽略",
].join("\n");

const ACCOUNT_IMPORT_PLACEHOLDER = [
  "每行一个账号：邮箱 密码（也可用 , : ---- 分隔）",
  "也可以直接粘贴 nai_const.py 里的 NAI_ACCOUNT 列表",
].join("\n");

function ImportSummary({
  result,
  onClose,
}: {
  result: NovelAITokenImportResult;
  onClose: () => void;
}) {
  const duplicates = result.skipped.filter((item) => item.reason === "duplicate").length;
  const loginFailed = result.skipped.filter((item) => item.reason === "login_failed").length;
  const invalid = result.skipped.length - duplicates - loginFailed;
  const requeued = result.requeued?.length ?? 0;
  const queued = result.added.some((entry) => entry.kind === "account") || requeued > 0;
  const parts = [
    result.imported_as === "accounts"
      ? `识别为账号密码，导入 ${result.added.length} 个账号`
      : `导入 ${result.added.length} 个`,
  ];
  if (requeued) parts.push(`重新排队 ${requeued} 个`);
  if (duplicates) parts.push(`跳过重复 ${duplicates} 个`);
  if (queued) parts.push("正在后台登录");
  if (loginFailed) parts.push(`登录失败 ${loginFailed} 个`);
  if (invalid) parts.push(`格式不对 ${invalid} 个`);
  return (
    <div
      className={result.added.length ? "popover-alert info" : "popover-alert warn"}
      role="status"
    >
      <div className="token-import-summary-head">
        <span>{parts.join("，")}</span>
        <button aria-label="关闭导入结果" className="token-icon" onClick={onClose} type="button">
          <X size={12} />
        </button>
      </div>
      {result.skipped.length ? (
        <ul className="token-import-skipped">
          {result.skipped.map((item) => (
            <li key={item.line}>
              第 {item.line} 行：{item.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function tierLabel(info: NovelAIUsageInfo): { text: string; tone: string; title: string } {
  if (info.error) {
    const invalid = /无效|过期|401|403/.test(info.error);
    return { text: invalid ? "失效" : "查询失败", tone: "danger", title: info.error };
  }
  if (!info.active || info.tier <= 0) {
    return { text: "无订阅", tone: "muted", title: "没有有效订阅，出图只能用点数" };
  }
  const tone = info.tier >= 3 ? "opus" : info.tier === 2 ? "scroll" : "tablet";
  return { text: info.tier_name, tone, title: `${info.tier_name} (Tier ${info.tier}) · 订阅有效` };
}

/** 账号还在后台排队登录，或登录失败：这时没有 token，不查用量。 */
function accountWaiting(entry: NovelAITokenEntry): boolean {
  return (
    entry.kind === "account" &&
    (entry.login_status === "pending" || entry.login_status === "failed")
  );
}

function LoginStatusTag({ entry }: { entry: NovelAITokenEntry }) {
  if (entry.login_status === "failed") {
    return (
      <span className="token-tier danger" title={entry.login_error ?? "登录失败"}>
        登录失败
      </span>
    );
  }
  return (
    <span className="token-tier muted" title={entry.login_error ?? "排队等待后台登录"}>
      <Loader2 className="spin" size={9} /> 排队登录
    </span>
  );
}

function TierTag({ info, loading }: { info?: NovelAIUsageInfo; loading: boolean }) {
  if (!info) {
    return loading ? (
      <Loader2 aria-label="查询中" className="spin token-tier-loading" size={11} />
    ) : null;
  }
  const label = tierLabel(info);
  return (
    <span className={`token-tier ${label.tone}`} title={label.title}>
      {label.text}
    </span>
  );
}

function UsageMeta({ info }: { info?: NovelAIUsageInfo }) {
  if (!info || info.error) return null;
  const v5Tone = info.usage_percent <= 0 ? "danger" : info.usage_percent <= 25 ? "warn" : "ok";
  return (
    <>
      <span
        className="token-anlas"
        title={`固定 ${info.fixed_anlas.toLocaleString()} / 购买 ${info.purchased_anlas.toLocaleString()}`}
      >
        {info.anlas.toLocaleString()} 点
      </span>
      {info.active && info.tier > 0 ? (
        <span className={`token-v5 ${v5Tone}`} title="V5 会员免费额度剩余">
          V5 {info.usage_percent.toFixed(0)}%
        </span>
      ) : null}
    </>
  );
}
