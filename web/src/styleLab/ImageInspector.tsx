import { AlertTriangle, Copy, ExternalLink, FolderOpen, UserRound } from "lucide-react";
import { useMemo, useState } from "react";

import type { ImageRecord } from "./api";
import { errorMessage } from "../api/client";
import { revealFile, sourceImageUrl } from "./api";
import { fileName, flagLabels, modelLabel } from "./format";
import { sourceViewerItem, useImageViewer } from "./ImageViewer";
import { splitPromptTags, translationStore, useTranslations } from "./translations";

const flagHints: Partial<Record<string, string>> = {
  no_metadata: "读不到 NovelAI 元数据（可能只有隐水印），无法原参重生。",
  inpaint: "局部重绘图：元数据里没有底图和蒙版，原参重生只能近似。",
  img2img: "图生图：元数据里没有底图，原参重生只能近似。",
  vibe_missing: "用了 vibe 但没有内嵌参考图，重生时缺少 vibe。",
  director_ref: "用了角色参考（director reference）。",
};

type ImageInspectorProps = {
  workspaceId: string;
  image: ImageRecord;
  translateOn: boolean;
  children?: React.ReactNode;
};

export function ImageInspector({ workspaceId, image, translateOn, children }: ImageInspectorProps) {
  const viewer = useImageViewer();
  const fullUrl = sourceImageUrl(workspaceId, image.id, 0);
  const hints = image.flags.map((flag) => flagHints[flag]).filter(Boolean) as string[];

  return (
    <div className="sl-inspector-body">
      <header className="sl-inspector-head">
        <div className="sl-inspector-title">
          <strong title={image.path}>{fileName(image.path)}</strong>
          <span>
            {[image.post?.date, image.post?.post_id, image.post?.title].filter(Boolean).join(" · ") || image.rel_path}
          </span>
        </div>
        <button
          aria-label="打开所在位置"
          className="sl-icon-btn"
          onClick={() => void revealFile(workspaceId, { imageId: image.id }).catch((error) => window.alert(errorMessage(error)))}
          title="在资源管理器中打开所在位置"
          type="button"
        >
          <FolderOpen size={15} />
        </button>
        <a aria-label="在新标签页打开原图" className="sl-icon-btn" href={fullUrl} rel="noreferrer" target="_blank" title="打开原图">
          <ExternalLink size={15} />
        </a>
      </header>

      <button className="sl-preview sl-zoomable" onClick={() => viewer.open([sourceViewerItem(image)])} title="查看大图和文件位置" type="button">
        <img alt={fileName(image.path)} src={sourceImageUrl(workspaceId, image.id, 640)} />
      </button>

      {hints.length ? (
        <div className="sl-warn">
          <AlertTriangle size={15} aria-hidden="true" />
          <div>
            {hints.map((hint) => (
              <p key={hint}>{hint}</p>
            ))}
          </div>
        </div>
      ) : null}

      {image.has_metadata ? (
        <>
          <PromptSection title="提示词" text={image.prompt} translateOn={translateOn} />
          <CharacterSection image={image} translateOn={translateOn} />
          <PromptSection collapsible title="负面" text={image.negative_prompt} translateOn={translateOn} />
          <ParamsTable image={image} />
        </>
      ) : null}

      {children}
    </div>
  );
}

function PromptSection({
  title,
  text,
  translateOn,
  collapsible = false,
}: {
  title: string;
  text: string;
  translateOn: boolean;
  collapsible?: boolean;
}) {
  const [open, setOpen] = useState(!collapsible);
  const tags = useMemo(() => splitPromptTags(text), [text]);

  return (
    <section className="sl-section">
      <header className="sl-section-head">
        <button className="sl-section-toggle" onClick={() => setOpen(!open)} type="button">
          {title}
          <span className="sl-count">{tags.length}</span>
        </button>
        <CopyButton text={text} />
      </header>
      {open ? <TagList tags={tags} translateOn={translateOn} /> : null}
    </section>
  );
}

function CharacterSection({ image, translateOn }: { image: ImageRecord; translateOn: boolean }) {
  return (
    <section className="sl-section">
      <header className="sl-section-head">
        <span className="sl-section-label">
          <UserRound size={14} aria-hidden="true" />
          角色提示词
          <span className="sl-count">{image.char_captions.length}</span>
        </span>
      </header>
      {image.char_captions.length === 0 ? (
        <p className="sl-muted">原图没有角色提示词，内容都在基础提示词里。</p>
      ) : (
        image.char_captions.map((caption, index) => (
          <div className="sl-char" key={index}>
            <div className="sl-char-head">
              <span>#{index + 1}</span>
              {caption.centers[0] ? (
                <span className="sl-muted">
                  位置 {caption.centers[0].x.toFixed(1)}, {caption.centers[0].y.toFixed(1)}
                </span>
              ) : null}
              <CopyButton text={caption.positive} />
            </div>
            <TagList tags={splitPromptTags(caption.positive)} translateOn={translateOn} />
            {caption.negative ? (
              <p className="sl-char-negative">负面：{caption.negative}</p>
            ) : null}
          </div>
        ))
      )}
    </section>
  );
}

export function TagList({ tags, translateOn }: { tags: string[]; translateOn: boolean }) {
  const { lookup } = useTranslations(tags, translateOn);
  if (!tags.length) {
    return <p className="sl-muted">（空）</p>;
  }
  return (
    <div className="sl-tags">
      {tags.map((tag, index) => {
        const zh = lookup(tag);
        return (
          <span className="sl-tag" key={`${tag}-${index}`} title={tag}>
            <span className="sl-tag-en">{tag}</span>
            {translateOn && (zh || translationStore.isPending(tag)) ? (
              <span className="sl-tag-zh">{zh ?? "…"}</span>
            ) : null}
          </span>
        );
      })}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      aria-label="复制"
      className="sl-icon-btn"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        });
      }}
      title={copied ? "已复制" : "复制原文"}
      type="button"
    >
      <Copy size={14} />
      {copied ? <span className="sl-copied">已复制</span> : null}
    </button>
  );
}

function ParamsTable({ image }: { image: ImageRecord }) {
  const rows: Array<[string, string]> = [
    ["模型", `${modelLabel(image.model)}${image.model ? ` (${image.model})` : ""}`],
    ["尺寸", image.width && image.height ? `${image.width} × ${image.height}` : "—"],
    ["种子", image.seed?.toString() ?? "—"],
    ["采样", [image.sampler, image.noise_schedule].filter(Boolean).join(" · ") || "—"],
    ["步数 / CFG", `${image.steps ?? "—"} / ${image.scale ?? "—"}`],
    ["CFG rescale", image.cfg_rescale?.toString() ?? "—"],
    [
      "Vibe",
      image.vibe.count
        ? image.vibe.hashes
            .map(
              (hash, index) =>
                `${hash} · 强度 ${image.vibe.strengths[index] ?? "—"} · 信息 ${image.vibe.information_extracted[index] ?? "—"}`,
            )
            .join("\n")
        : image.vibe.strengths.length
          ? "有参数，无内嵌图"
          : "无",
    ],
    ["请求类型", image.request_type ?? "—"],
    ["标记", image.flags.map((flag) => flagLabels[flag]).join("、") || "无"],
  ];
  return (
    <section className="sl-section">
      <header className="sl-section-head">
        <span className="sl-section-label">参数</span>
      </header>
      <dl className="sl-params">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
