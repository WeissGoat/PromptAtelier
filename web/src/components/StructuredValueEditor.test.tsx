import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StructuredValueEditor } from "./StructuredValueEditor";

describe("StructuredValueEditor", () => {
  afterEach(cleanup);

  it("updates nested values without dropping sibling fields", () => {
    const onChange = vi.fn();
    render(<StructuredValueEditor onChange={onChange} path={["extensions"]} value={{ enabled: true, nested: { count: 2, keep: "yes" } }} />);

    fireEvent.change(screen.getByLabelText("extensions.nested.count"), { target: { value: "3" } });

    expect(onChange).toHaveBeenCalledWith({ enabled: true, nested: { count: 3, keep: "yes" } });
  });

  it("adds and removes array entries", () => {
    const onChange = vi.fn();
    const view = render(<StructuredValueEditor onChange={onChange} path={["tags", "action"]} value={["standing"]} />);
    fireEvent.click(screen.getByRole("button", { name: "添加 tags.action 项" }));
    expect(onChange).toHaveBeenCalledWith(["standing", ""]);

    view.rerender(<StructuredValueEditor onChange={onChange} path={["tags", "action"]} value={["standing", "walking"]} />);
    fireEvent.click(screen.getByRole("button", { name: "删除 tags.action.0" }));
    expect(onChange).toHaveBeenCalledWith(["walking"]);
  });

  it("adds an object property with the selected type", () => {
    const onChange = vi.fn();
    render(<StructuredValueEditor onChange={onChange} path={["extensions"]} value={{}} />);
    fireEvent.change(screen.getByLabelText("extensions new property"), { target: { value: "weight" } });
    fireEvent.change(screen.getByLabelText("extensions new value type"), { target: { value: "number" } });
    fireEvent.click(screen.getByRole("button", { name: "添加 extensions 项" }));
    expect(onChange).toHaveBeenCalledWith({ weight: 0 });
  });
});
