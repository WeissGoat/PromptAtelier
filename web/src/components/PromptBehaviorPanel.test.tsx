import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createDefaultPromptBehavior } from "../workspace/storage";
import type { PromptBehaviorParams } from "../workspace/types";
import { PromptBehaviorPanel } from "./PromptBehaviorPanel";

describe("PromptBehaviorPanel", () => {
  afterEach(cleanup);

  it("defaults to auto character prompts and inherited policy rules", () => {
    render(<PromptBehaviorPanel characterSections={["character", "role", "hair"]} onChange={vi.fn()} value={createDefaultPromptBehavior()} />);

    expect((screen.getByLabelText("Character Prompts Auto") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("Visibility Policy state") as HTMLSelectElement).value).toBe("inherit");
  });

  it("marks the NovelAI-only options when ComfyUI artists are in the workspace", () => {
    const view = render(<PromptBehaviorPanel characterSections={[]} onChange={vi.fn()} value={createDefaultPromptBehavior()} />);
    expect(screen.queryByText("ComfyUI 画风不使用此项")).toBeNull();

    view.rerender(<PromptBehaviorPanel characterSections={[]} comfyuiArtists onChange={vi.fn()} value={createDefaultPromptBehavior()} />);

    expect(screen.getAllByText("ComfyUI 画风不使用此项")).toHaveLength(2);
  });

  it("does not allow removing the last identity section", () => {
    const value: PromptBehaviorParams = {
      ...createDefaultPromptBehavior(),
      identityMinimal: { mode: "override", sections: ["character"] },
    };
    const onChange = vi.fn();
    render(<PromptBehaviorPanel characterSections={["character"]} onChange={onChange} value={value} />);

    fireEvent.click(screen.getByLabelText("Identity section character"));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/At least one section/)).not.toBeNull();
  });

  it("shows advanced options only for enabled rules", () => {
    const onChange = vi.fn();
    const view = render(<PromptBehaviorPanel characterSections={[]} onChange={onChange} value={createDefaultPromptBehavior()} />);

    expect(screen.queryByLabelText("Visibility mode")).toBeNull();
    fireEvent.change(screen.getByLabelText("Visibility Policy state"), { target: { value: "enabled" } });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      policyRules: expect.objectContaining({ visibility_policy: { state: "enabled" } }),
    }));
    view.rerender(<PromptBehaviorPanel characterSections={[]} onChange={onChange} value={{
      ...createDefaultPromptBehavior(),
      policyRules: { visibility_policy: { state: "enabled" } },
    }} />);
    expect(screen.getByLabelText("Visibility mode")).not.toBeNull();
  });
});
