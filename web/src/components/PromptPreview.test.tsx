import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PromptPreview } from "./PromptPreview";

describe("PromptPreview", () => {
  afterEach(cleanup);

  it("summarizes a ComfyUI render request with the prompt it actually receives", () => {
    render(
      <PromptPreview
        negative="[lowres]"
        prompt="{{1girl}}, smile"
        renderRequest={{
          backend: "comfyui",
          prompt: "{{1girl}}, smile",
          negative_prompt: "[lowres]",
          seed: 42,
          size: { width: 832, height: 1216 },
          params: {
            workflow: "cunyfunky",
            positive_prompt: "(1girl:1.1025), smile",
            negative_prompt: "(lowres:0.9524)",
            steps: 30,
            cfg: 6.5,
          },
        }}
      />,
    );

    expect(screen.getByText("ComfyUI")).toBeTruthy();
    expect(screen.getByText("cunyfunky")).toBeTruthy();
    expect(screen.getByText("832 × 1216")).toBeTruthy();
    expect(screen.getByText("6.5")).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
    expect((screen.getByLabelText("ComfyUI positive preview") as HTMLTextAreaElement).value).toBe("(1girl:1.1025), smile");
    expect((screen.getByLabelText("ComfyUI negative preview") as HTMLTextAreaElement).value).toBe("(lowres:0.9524)");
  });

  it("keeps NovelAI previews free of ComfyUI rows", () => {
    render(
      <PromptPreview
        negative=""
        prompt="1girl"
        renderRequest={{
          backend: "novelai",
          prompt: "1girl",
          model: "nai-diffusion-4-5-full",
          seed: 7,
          size: { width: 832, height: 1216 },
          params: { n_samples: 1 },
        }}
      />,
    );

    expect(screen.queryByText("Backend")).toBeNull();
    expect(screen.getByText("nai-diffusion-4-5-full")).toBeTruthy();
    expect(screen.getByText("832 × 1216")).toBeTruthy();
    expect(screen.queryByLabelText("ComfyUI positive preview")).toBeNull();
  });
});
