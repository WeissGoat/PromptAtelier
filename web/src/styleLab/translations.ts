import { useEffect, useMemo, useSyncExternalStore } from "react";

import { translateTexts, type TranslateProvider } from "./api";
import { tokenize } from "./tokens";

/** 提示词按无损分词器切成 token（权重组、括号组保持完整），和后端分析任务用同一套规则。 */
export function splitPromptTags(prompt: string): string[] {
  return tokenize(prompt ?? "").tokens.map((token) => token.text);
}

/** 一块的译文：块里每个 tag 各查各的再拼起来；一个都没查到时返回 undefined。 */
export function blockTranslation(text: string, lookup: (tag: string) => string | undefined): string | undefined {
  const parts = splitPromptTags(text);
  if (parts.length <= 1) return lookup(text);
  const found = parts.map((part) => lookup(part));
  return found.some(Boolean) ? found.map((zh, index) => zh ?? parts[index]).join("，") : undefined;
}

type Listener = () => void;

/**
 * 页面级翻译缓存：各组件只登记要翻的 tag，短时间内的请求合并成一次；
 * 翻不出来的 tag 记为失败，同一页面里不再重复请求。
 */
class TranslationStore {
  private translations = new Map<string, string>();
  private failed = new Set<string>();
  private queued = new Set<string>();
  private inflight = new Set<string>();
  private listeners = new Set<Listener>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private version = 0;
  pending = 0;
  /** retryFailed 之后加一，让已挂载的组件重新登记自己的 tag。 */
  retryGeneration = 0;
  provider: TranslateProvider = "google";

  /** 换翻译来源：清掉已有译文，已挂载的组件按新来源重新请求。 */
  setProvider(provider: TranslateProvider): void {
    if (provider === this.provider) return;
    this.provider = provider;
    this.translations.clear();
    this.failed.clear();
    this.queued.clear();
    this.retryGeneration += 1;
    this.emit();
  }

  subscribe = (listener: Listener) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getVersion = () => this.version;

  /** 之前没翻出来的 tag 允许再请求一次（例如后台预翻译刚跑完）。 */
  retryFailed(): void {
    if (this.failed.size) {
      this.failed.clear();
      this.retryGeneration += 1;
      this.emit();
    }
  }

  get(tag: string): string | undefined {
    return this.translations.get(tag);
  }

  /** 还在排队或请求中；翻译失败或无可翻译内容（如单独的 "::"）返回 false。 */
  isPending(tag: string): boolean {
    return this.queued.has(tag) || this.inflight.has(tag);
  }

  request(tags: string[]): void {
    let added = false;
    for (const tag of tags) {
      if (!tag || this.translations.has(tag) || this.failed.has(tag) || this.inflight.has(tag) || this.queued.has(tag)) {
        continue;
      }
      this.queued.add(tag);
      added = true;
    }
    if (added && this.timer === null) {
      this.timer = setTimeout(() => this.flush(), 60);
    }
  }

  private async flush(): Promise<void> {
    this.timer = null;
    const batch = [...this.queued].slice(0, 2000);
    batch.forEach((tag) => {
      this.queued.delete(tag);
      this.inflight.add(tag);
    });
    if (this.queued.size > 0) {
      this.timer = setTimeout(() => this.flush(), 60);
    }
    this.pending += 1;
    this.emit();
    const provider = this.provider;
    try {
      const response = await translateTexts(batch, provider);
      // 请求途中换了来源：这批结果作废。
      if (provider !== this.provider) return;
      for (const tag of batch) {
        const value = response.translations[tag];
        if (value) {
          this.translations.set(tag, value);
        } else {
          this.failed.add(tag);
        }
      }
    } catch {
      batch.forEach((tag) => this.failed.add(tag));
    } finally {
      batch.forEach((tag) => this.inflight.delete(tag));
      this.pending -= 1;
      this.emit();
    }
  }

  private emit(): void {
    this.version += 1;
    this.listeners.forEach((listener) => listener());
  }
}

export const translationStore = new TranslationStore();

/** 登记一批 tag 的翻译需求，返回当前已有的译文（随结果陆续到达自动刷新）。 */
export function useTranslations(tags: string[], enabled: boolean): { lookup: (tag: string) => string | undefined; pending: boolean } {
  const version = useSyncExternalStore(translationStore.subscribe, translationStore.getVersion);
  const key = tags.join("\u0000");
  const retry = translationStore.retryGeneration;
  useEffect(() => {
    if (enabled) {
      translationStore.request(tags);
    }
    // tags 的内容由 key 代表。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, retry]);
  return useMemo(
    () => ({
      lookup: (tag: string) => (enabled ? translationStore.get(tag) : undefined),
      pending: enabled && translationStore.pending > 0,
    }),
    // version 变化代表有新译文。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [version, enabled],
  );
}
