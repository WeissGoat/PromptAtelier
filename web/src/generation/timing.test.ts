import { describe, expect, it } from "vitest";

import { formatDuration, formatImageTiming } from "./timing";

describe("formatDuration", () => {
  it("shows seconds under a minute and minutes above", () => {
    expect(formatDuration(7.25)).toBe("7.3 秒");
    expect(formatDuration(78.4)).toBe("1 分 18 秒");
    expect(formatDuration(120)).toBe("2 分");
  });
});

describe("formatImageTiming", () => {
  it("returns null for images without timing", () => {
    expect(formatImageTiming(undefined)).toBeNull();
    expect(formatImageTiming({ seed: 1 })).toBeNull();
  });

  it("uses the total time when there is no execution time", () => {
    expect(formatImageTiming({ elapsed_seconds: 12.3 })).toBe("12.3 秒");
  });

  it("prefers ComfyUI execution time and notes long waits", () => {
    expect(formatImageTiming({ elapsed_seconds: 80.1, execution_seconds: 78.4 })).toBe("1 分 18 秒");
    expect(formatImageTiming({ elapsed_seconds: 140, execution_seconds: 78.4 })).toBe("1 分 18 秒（含等待共 2 分 20 秒）");
  });
});
