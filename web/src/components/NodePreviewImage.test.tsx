import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { NodePreviewImage } from "./NodePreviewImage";

describe("NodePreviewImage", () => {
  afterEach(cleanup);

  it("shows the cached thumbnail and opens the original in a lightbox", () => {
    render(<NodePreviewImage name="standing" nodeRef="F:/design/动作/standing" />);

    const thumb = screen.getByRole("img", { name: "standing 预览图" }) as HTMLImageElement;
    expect(thumb.src).toContain("/nodes/preview-image?ref=F%3A%2Fdesign%2F%E5%8A%A8%E4%BD%9C%2Fstanding&size=240");

    fireEvent.click(screen.getByRole("button", { name: "查看 standing 预览大图" }));
    const lightbox = screen.getByRole("dialog", { name: "standing 大图" });
    expect((lightbox.querySelector("img") as HTMLImageElement).src).toContain("&size=0");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows a placeholder when the node has no image or the image fails to load", () => {
    const { rerender } = render(<NodePreviewImage hasPreview={false} name="homura" nodeRef="F:/design/角色/homura" />);
    expect(screen.getByRole("img", { name: "homura 没有预览图" })).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();

    rerender(<NodePreviewImage name="madoka" nodeRef="F:/design/角色/madoka" />);
    fireEvent.error(screen.getByRole("img", { name: "madoka 预览图" }));
    expect(screen.getByRole("img", { name: "madoka 没有预览图" })).toBeTruthy();
  });
});
