import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CustomWorkspaceProvider } from "../workspace/CustomWorkspaceProvider";
import { PromptBehaviorGroupPanel } from "./PromptBehaviorGroupPanel";

function renderPanel() {
  render(
    <CustomWorkspaceProvider>
      <PromptBehaviorGroupPanel characterSections={["character", "role", "hair"]} />
    </CustomWorkspaceProvider>,
  );
}

describe("PromptBehaviorGroupPanel", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("mirrors the primary behavior into an independently editable compare", () => {
    renderPanel();
    expect(screen.getByText("Primary")).toBeTruthy();
    expect((screen.getByLabelText("Character Prompts Auto") as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByLabelText("Add Prompt Behavior Compare"));
    expect(screen.getByText("Compare 1")).toBeTruthy();
    expect((screen.getByLabelText("Prompt Behavior label") as HTMLInputElement).value).toBe("Compare 1");

    fireEvent.click(screen.getByLabelText("Character Prompts Off"));
    expect((screen.getByLabelText("Character Prompts Off") as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByLabelText("Select Prompt Behavior Default"));
    expect((screen.getByLabelText("Character Prompts Auto") as HTMLInputElement).checked).toBe(true);
  });

  it("renames and removes a compare behavior", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel();
    fireEvent.click(screen.getByLabelText("Add Prompt Behavior Compare"));

    const label = screen.getByLabelText("Prompt Behavior label");
    fireEvent.change(label, { target: { value: "No Character Prompts" } });
    fireEvent.blur(label);
    expect(screen.getByText("No Character Prompts")).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Remove Prompt Behavior No Character Prompts"));
    expect(screen.queryByText("No Character Prompts")).toBeNull();
    expect((screen.getByLabelText("Prompt Behavior label") as HTMLInputElement).value).toBe("Default");
  });
});
