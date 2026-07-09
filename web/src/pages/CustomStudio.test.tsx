import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CustomStudio } from "./CustomStudio";

describe("CustomStudio", () => {
  it("renders node selectors and prompt preview", () => {
    render(<CustomStudio />);

    expect(screen.getByText("Artist")).toBeTruthy();
    expect(screen.getByText("Character")).toBeTruthy();
    expect(screen.getByText("Action")).toBeTruthy();
    expect(screen.getByText("Prompt Preview")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Preview" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Generate" })).toBeTruthy();
  });
});
