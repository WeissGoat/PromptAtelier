import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BatchStudio } from "./BatchStudio";

describe("BatchStudio", () => {
  it("renders batch controls and preview action", () => {
    render(<BatchStudio />);

    expect(screen.getByText("Batch Studio")).toBeTruthy();
    expect(screen.getByLabelText("Characters")).toBeTruthy();
    expect(screen.getByLabelText("Action Groups")).toBeTruthy();
    expect(screen.getByLabelText("Artist")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Plan Preview" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run Batch" })).toBeTruthy();
  });
});
