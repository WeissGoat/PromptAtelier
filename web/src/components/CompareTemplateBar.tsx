import { Image as ImageIcon, Lock, RotateCcw, UploadCloud } from "lucide-react";
import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { apiPost, errorMessage } from "../api/client";
import type { BaseTemplate } from "../compare/types";
import { useCompareWorkspace } from "../compare/useCompareWorkspace";

export function CompareTemplateBar() {
  const { state, setBaseTemplate, clearWorkspace } = useCompareWorkspace();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const template = state.template;
  const hasTemplate = Boolean(template.prompt.trim() || template.sourceImage);

  async function handleFile(file: File) {
    if (!file.type.startsWith("image/") && !file.name.toLowerCase().endsWith(".png")) {
      setError("请上传 PNG 或常见图片格式文件。");
      return;
    }

    setBusy(true);
    setError("");

    try {
      const reader = new FileReader();
      const base64Data = await new Promise<string>((resolve, reject) => {
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("读取本地文件失败"));
        reader.readAsDataURL(file);
      });

      const inspected = await apiPost<{
        filename: string;
        dimensions: { width: number; height: number };
        prompt: string;
        negative_prompt: string;
        seed: number | null;
        steps: number;
        scale: number;
        sampler: string | null;
        model: string | null;
      }>("/image-meta/inspect", {
        image_base64: base64Data,
        filename: file.name,
      });

      const newTemplate: BaseTemplate = {
        prompt: inspected.prompt,
        negative: inspected.negative_prompt,
        seed: inspected.seed ?? Math.floor(Math.random() * 0x1_0000_0000),
        width: inspected.dimensions?.width ?? 1024,
        height: inspected.dimensions?.height ?? 1024,
        steps: inspected.steps ?? 28,
        scale: inspected.scale ?? 5.0,
        sampler: inspected.sampler || "k_euler",
        model: inspected.model || "nai-diffusion-3",
        sourceImage: {
          previewUrl: base64Data,
          filename: inspected.filename,
        },
      };

      setBaseTemplate(newTemplate);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) {
      void handleFile(file);
      event.target.value = "";
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file) {
      void handleFile(file);
    }
  }

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
  }

  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      const items = event.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) {
            void handleFile(file);
            break;
          }
        }
      }
    }

    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  return (
    <section className="panel compare-template-bar">
      <input
        accept="image/png,image/jpeg,image/webp"
        onChange={onFileChange}
        ref={fileInputRef}
        style={{ display: "none" }}
        type="file"
      />

      <div className="template-bar-header">
        <div className="template-title-group">
          <h2>Base Template (基准底模)</h2>
          <span className="hint-pill">控制变量锁定</span>
        </div>
        {hasTemplate ? (
          <button
            className="secondary-button compact"
            onClick={clearWorkspace}
            title="清空重置工作区"
            type="button"
          >
            <RotateCcw size={14} /> 重置
          </button>
        ) : null}
      </div>

      {error ? <div className="alert error-alert">{error}</div> : null}

      <div
        className={`template-dropzone ${busy ? "busy" : ""} ${hasTemplate ? "has-data" : ""}`}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={onDragOver}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
      >
        {template.sourceImage?.previewUrl ? (
          <div className="template-preview-thumbnail">
            <img alt="Source preview" src={template.sourceImage.previewUrl} />
          </div>
        ) : (
          <div className="template-dropzone-icon">
            <UploadCloud size={24} />
          </div>
        )}

        <div className="template-dropzone-content">
          <div className="dropzone-text-primary">
            {busy
              ? "正在解析图片元数据..."
              : hasTemplate
              ? `已读入: ${template.sourceImage?.filename || "图片参数模板"}`
              : "拖拽 PNG 图片至此处，或 Ctrl + V 粘贴图片读入参数生成模板"}
          </div>
          <div className="dropzone-text-secondary">
            支持 NovelAI / WebUI 包含元数据的生成图，自动提取 Prompt、Seed、分辨率与采样参数
          </div>
        </div>

        <button
          className="upload-action-btn"
          disabled={busy}
          onClick={(e) => {
            e.stopPropagation();
            fileInputRef.current?.click();
          }}
          type="button"
        >
          <ImageIcon size={14} /> 选取图片
        </button>
      </div>

      {hasTemplate ? (
        <div className="template-parameters-summary">
          <div className="parameter-tags-row">
            <span className="param-badge locked">
              <Lock size={12} /> Seed: {template.seed}
            </span>
            <span className="param-badge">
              尺寸: {template.width} × {template.height}
            </span>
            <span className="param-badge">步数: {template.steps}</span>
            <span className="param-badge">Scale: {template.scale}</span>
            {template.sampler ? <span className="param-badge">{template.sampler}</span> : null}
            {template.model ? <span className="param-badge">{template.model}</span> : null}
          </div>

          {template.prompt ? (
            <div className="template-prompt-display">
              <span className="field-label">底模基准提示词:</span>
              <p className="base-prompt-text">{template.prompt}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
