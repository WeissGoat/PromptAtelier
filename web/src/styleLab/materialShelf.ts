/**
 * 全局素材架的前端缓存：页面里只读一次，改动立即生效并按顺序存回后端（连点几下只发最后一版）。
 */
import { useEffect, useState } from "react";

import { errorMessage } from "../api/client";
import type { MaterialShelf } from "./api";
import { getShelf, saveShelf } from "./api";

const EMPTY: MaterialShelf = { materials: [], facets: {} };

type Change = (shelf: MaterialShelf) => MaterialShelf;

let current: MaterialShelf = EMPTY;
let loaded: Promise<void> | null = null;
let ready = false;
/** 后端读回来之前的改动：读回来后在后端的版本上重放，不能用本地空架子覆盖后端。 */
let early: Change[] = [];
let saving = false;
let dirty = false;
let lastError: string | null = null;
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

function ensureLoaded() {
  loaded ??= getShelf()
    .then((data) => {
      const base: MaterialShelf = { materials: data.materials ?? [], facets: data.facets ?? {} };
      current = early.reduce((shelf, change) => change(shelf), base);
      ready = true;
      if (early.length) void flush();
      early = [];
    })
    .catch((error) => {
      lastError = errorMessage(error);
      loaded = null;
    })
    .finally(notify);
}

async function flush() {
  if (saving) {
    dirty = true;
    return;
  }
  saving = true;
  try {
    do {
      dirty = false;
      await saveShelf(current);
      lastError = null;
    } while (dirty);
  } catch (error) {
    lastError = `素材架保存失败：${errorMessage(error)}`;
  } finally {
    saving = false;
    notify();
  }
}

export function updateShelf(change: Change) {
  const next = change(current);
  if (next === current) return;
  current = next;
  notify();
  if (ready) void flush();
  else early.push(change);
}

export function useMaterialShelf(): { shelf: MaterialShelf; ready: boolean; error: string | null } {
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener = () => setTick((tick) => tick + 1);
    listeners.add(listener);
    ensureLoaded();
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return { shelf: current, ready, error: lastError };
}

/** 测试用：清掉模块里的缓存。 */
export function resetShelfForTests() {
  current = EMPTY;
  loaded = null;
  ready = false;
  early = [];
  saving = false;
  dirty = false;
  lastError = null;
}
