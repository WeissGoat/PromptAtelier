import { beforeEach, describe, expect, it } from "vitest";

import {
  filterNodePickerHistory,
  loadNodePickerHistory,
  mergeHistoryAndResults,
  NODE_PICKER_HISTORY_STORAGE_KEY,
  recordNodePickerSelection,
} from "./pickerHistory";

describe("pickerHistory", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("records selections per role in most-recently-selected order and deduplicates by ref", () => {
    recordNodePickerSelection("action", { role: "action", name: "first", ref: "F:/a/first" });
    recordNodePickerSelection("action", { role: "action", name: "second", ref: "F:/a/second" });
    recordNodePickerSelection("character", { role: "character", name: "miku", ref: "F:/c/miku" });
    recordNodePickerSelection("action", { role: "action", name: "first", ref: "F:/a/first" });

    expect(loadNodePickerHistory("action").map((item) => item.ref)).toEqual(["F:/a/first", "F:/a/second"]);
    expect(loadNodePickerHistory("character").map((item) => item.ref)).toEqual(["F:/c/miku"]);
  });

  it("recovers gracefully from corrupted storage", () => {
    localStorage.setItem(NODE_PICKER_HISTORY_STORAGE_KEY, "{broken");
    expect(loadNodePickerHistory("action")).toEqual([]);
  });

  it("filters history by multi-token query across name and relative path", () => {
    const history = [
      { role: "action", name: "standing", ref: "F:/a/1", relative: "solo/standing" },
      { role: "action", name: "sitting", ref: "F:/a/2", relative: "duo/sitting" },
    ];
    expect(filterNodePickerHistory(history, "solo stand").map((item) => item.name)).toEqual(["standing"]);
    expect(filterNodePickerHistory(history, "").map((item) => item.name)).toEqual(["standing", "sitting"]);
  });

  it("pins history before remaining results and refreshes metadata from fresh results", () => {
    const history = [
      { role: "action", name: "old-selected", ref: "F:/a/old", has_preview: false },
      { role: "action", name: "shared", ref: "F:/a/shared", has_preview: false },
    ];
    const results = [
      { role: "action", name: "newest", ref: "F:/a/newest", has_preview: true },
      { role: "action", name: "shared-renamed", ref: "F:/a/shared", has_preview: true },
      { role: "action", name: "second-newest", ref: "F:/a/second", has_preview: false },
    ];
    const merged = mergeHistoryAndResults(history, results);
    expect(merged.map((item) => item.ref)).toEqual([
      "F:/a/old",
      "F:/a/shared",
      "F:/a/newest",
      "F:/a/second",
    ]);
    expect(merged[1].name).toBe("shared-renamed");
    expect(merged[1].has_preview).toBe(true);
  });
});
