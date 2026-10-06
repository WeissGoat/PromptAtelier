import { ImageOff, X } from "lucide-react";
import { useEffect, useState } from "react";

import { nodePreviewUrl } from "../api/client";

type Props = {
  nodeRef: string;
  name: string;
  /** 列表接口已经告诉我们有没有图；不知道时（undefined）先试着加载，404 再显示占位。 */
  hasPreview?: boolean;
  size?: number;
  className?: string;
  /** 点击看大图；关掉时只显示缩略图。 */
  zoomable?: boolean;
};

export function ImageLightbox({ src, title, onClose }: { src: string; title: string; onClose(): void }) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div aria-label={`${title} 大图`} aria-modal="true" className="image-lightbox" onClick={onClose} role="dialog">
      <figure onClick={(event) => event.stopPropagation()}>
        <img alt={title} src={src} />
        <figcaption>
          <span>{title}</span>
          <button aria-label="关闭大图" className="icon-button" onClick={onClose} type="button"><X size={16} /></button>
        </figcaption>
      </figure>
    </div>
  );
}

/** 节点预览图（规则：目录里最早的原图，没有就最早的任意图，再没有显示占位）。 */
export function NodePreviewImage({ nodeRef, name, hasPreview, size = 240, className = "", zoomable = true }: Props) {
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => setFailed(false), [nodeRef]);

  if (hasPreview === false || failed) {
    return (
      <span aria-label={`${name} 没有预览图`} className={`node-preview node-preview-empty ${className}`} role="img" title="节点目录里没有图片">
        <ImageOff size={16} />
      </span>
    );
  }
  const image = <img alt={`${name} 预览图`} decoding="async" loading="lazy" onError={() => setFailed(true)} src={nodePreviewUrl(nodeRef, size)} />;
  if (!zoomable) return <span className={`node-preview ${className}`}>{image}</span>;
  return (
    <>
      <button
        aria-label={`查看 ${name} 预览大图`}
        className={`node-preview ${className}`}
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
        type="button"
      >
        {image}
      </button>
      {open ? <ImageLightbox onClose={() => setOpen(false)} src={nodePreviewUrl(nodeRef, 0)} title={name} /> : null}
    </>
  );
}
