import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createEmptyClassifyFilter } from "../randomNodes/spec";
import type { ClassifyFilter } from "../workspace/types";
import { ClassifyFilterEditor } from "./ClassifyFilterEditor";

function Harness({ onChange = vi.fn() }: { onChange?: (value: ClassifyFilter) => void }) {
  const [value, setValue] = useState(createEmptyClassifyFilter());
  return (
    <ClassifyFilterEditor
      facets={{ domain: ["custom_domain"] }}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
      value={value}
    />
  );
}

function addDomain() {
  fireEvent.click(screen.getByRole("button", { name: "添加筛选" }));
  fireEvent.click(screen.getByRole("menuitem", { name: /Domain/ }));
}

afterEach(cleanup);

describe("ClassifyFilterEditor", () => {
  it("adds a field and selects multiple values without modifier keys", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    addDomain();
    fireEvent.click(screen.getByRole("checkbox", { name: "foot" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "body" }));

    expect(screen.getByRole("button", { name: "移除 Domain foot" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "移除 Domain body" })).toBeTruthy();
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ domain: ["foot", "body"] }));
  });

  it("removes individual chips and drops the field after its final value", () => {
    render(<Harness />);
    addDomain();
    fireEvent.click(screen.getByRole("checkbox", { name: "foot" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "body" }));

    fireEvent.click(screen.getByRole("button", { name: "移除 Domain foot" }));
    expect(screen.queryByRole("button", { name: "移除 Domain foot" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "移除 Domain body" }));
    expect(screen.queryByText("Domain")).toBeNull();
    expect(screen.getByText("未启用过滤")).toBeTruthy();
  });

  it("searches the option union and clears all active fields", () => {
    render(<Harness />);
    addDomain();
    fireEvent.change(screen.getByRole("textbox", { name: "搜索 Domain 值" }), { target: { value: "custom" } });
    expect(screen.getByRole("checkbox", { name: "custom_domain" })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: "foot" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "custom_domain" }));
    fireEvent.click(screen.getByRole("button", { name: "清空全部" }));
    expect(screen.getByText("未启用过滤")).toBeTruthy();
  });
});
