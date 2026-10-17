import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { TagSectionsField } from "./TagSectionsField";

function Harness({ initial }: { initial: Record<string, unknown> }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <TagSectionsField onChange={setValue} suggested={["legwear"]} value={value} />
      <pre data-testid="value">{JSON.stringify(value)}</pre>
    </>
  );
}

describe("TagSectionsField", () => {
  afterEach(cleanup);

  it("edits each section as comma separated tags and keeps typing intact", () => {
    render(<Harness initial={{ role: ["{{alternative_clothing}}"], upper_clothes: ["white shirt"], ears: [] }} />);
    const upper = screen.getByLabelText("upper_clothes 标签") as HTMLTextAreaElement;
    fireEvent.change(upper, { target: { value: "white shirt, " } });
    // 末尾逗号还在输入框里，数据里不会出现空标签。
    expect(upper.value).toBe("white shirt, ");
    fireEvent.change(upper, { target: { value: "white shirt, red scarf" } });
    expect(JSON.parse(screen.getByTestId("value").textContent!).upper_clothes).toEqual(["white shirt", "red scarf"]);

    // 空分区和建议分区收成按钮，点一下展开。
    expect(screen.queryByLabelText("ears 标签")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /腿部/ }));
    fireEvent.change(screen.getByLabelText("legwear 标签"), { target: { value: "black thighhighs" } });
    expect(JSON.parse(screen.getByTestId("value").textContent!).legwear).toEqual(["black thighhighs"]);

    fireEvent.click(screen.getByRole("button", { name: "删除分区 role" }));
    expect(JSON.parse(screen.getByTestId("value").textContent!).role).toBeUndefined();
  });
});
