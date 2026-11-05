import { beforeEach, describe, expect, it } from "vitest";

import { readSelectedFrames, readStored, STORAGE_KEYS, writeSelectedFrames, writeStored } from "./persist";

describe("agent studio persistence", () => {
  beforeEach(() => window.localStorage.clear());

  it("merges stored values over defaults so new fields keep their default", () => {
    writeStored(STORAGE_KEYS.settings, { artist: { ref: "artist/a", name: "a" }, nt: 3 });
    const value = readStored(STORAGE_KEYS.settings, { artist: null, nt: 1, size: "contract" });
    expect(value).toEqual({ artist: { ref: "artist/a", name: "a" }, nt: 3, size: "contract" });
  });

  it("falls back to defaults on broken or non-object data", () => {
    window.localStorage.setItem(STORAGE_KEYS.view, "{not json");
    expect(readStored(STORAGE_KEYS.view, { view: "marked" })).toEqual({ view: "marked" });
    window.localStorage.setItem(STORAGE_KEYS.view, "[1,2]");
    expect(readStored(STORAGE_KEYS.view, { view: "marked" })).toEqual({ view: "marked" });
  });

  it("remembers selected frames per contract, including an empty selection", () => {
    expect(readSelectedFrames("c1")).toBeNull();
    writeSelectedFrames("c1", ["f01", "f03"]);
    writeSelectedFrames("c2", []);
    expect(readSelectedFrames("c1")).toEqual(["f01", "f03"]);
    expect(readSelectedFrames("c2")).toEqual([]);
  });

  it("keeps only the most recently written contracts", () => {
    for (let index = 0; index < 55; index += 1) writeSelectedFrames(`contract-${index}`, ["f01"]);
    writeSelectedFrames("contract-0", ["f02"]);
    expect(readSelectedFrames("contract-0")).toEqual(["f02"]);
    expect(readSelectedFrames("contract-5")).toBeNull();
    expect(readSelectedFrames("contract-54")).toEqual(["f01"]);
  });
});
