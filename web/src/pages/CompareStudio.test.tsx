import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CompareStudio } from "./CompareStudio";

describe("CompareStudio", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders template bar with dropzone instructions", () => {
    render(<CompareStudio />);

    expect(screen.getByText(/拖拽 PNG 图片至此处/)).toBeTruthy();
    expect(screen.getByText(/读入参数生成模板/)).toBeTruthy();
  });

  it("renders '往下新增新的一批对比' button", () => {
    render(<CompareStudio />);

    const addRoundButton = screen.getByRole("button", {
      name: /往下新增新的一批对比/,
    });
    expect(addRoundButton).toBeTruthy();
  });

  it("allows clicking add round to create a new round section", () => {
    render(<CompareStudio />);

    const addRoundButton = screen.getByRole("button", {
      name: /往下新增新的一批对比/,
    });
    fireEvent.click(addRoundButton);

    expect(screen.getByText(/第 1 批对比/)).toBeTruthy();
    expect(screen.getByDisplayValue("变体 1-A")).toBeTruthy();
  });
});
