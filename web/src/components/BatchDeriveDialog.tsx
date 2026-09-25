import { FileImage, GitFork, Loader2, Play, Trash2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { apiPost, apiUrl, errorMessage } from "../api/client";
import type { BaseTemplate, CompareRound } from "../compare/types";

export type ParsedImageItem = {
  id: string;
  file: File;
  filename: string;
  cleanName: string;
  previewUrl: string;
  template?: BaseTemplate;
  status: "inspecting" | "ready" | "error";
  error?: string;
};

export type BatchDeriveDialogProps = {
  isOpen: boolean;
  sourceRound: CompareRound;
  onClose: () => void;
  onConfirm: (
    items: Array<{ template: BaseTemplate; filename: string }>,
    autoRun: boolean,
  ) => void;
};

export function BatchDeriveDialog({
  isOpen,
  sourceRound,
  onClose,
  onConfirm,
}: BatchDeriveDialogProps) {
  const [items, setItems] = useState<ParsedImageItem[]>([]);
  const [autoRun, setAutoRun] = useState(true);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Reset items when dialog opens/closes
  useEffect(() => {
    if (!isOpen) {
      setItems([]);
      setIsDraggingOver(false);
    }
  }, [isOpen]);

  // Handle escape key
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  const inspectSingleFile = useCallback(async (file: File): Promise<ParsedImageItem> => {
    const cleanName = file.name.replace(/\.[^/.]+$/, "");
    const id = `item_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

    try {
      const reader = new FileReader();
      const base64Data = await new Promise<string>((resolve, reject) => {
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error("读取本地文件失败"));
        reader.readAsDataURL(file);
      });

      const inspected = await apiPost<{
        filename: string;
        source_path?: string | null;
        dimensions: { width: number; height: number };
        prompt: string;
        negative_prompt: string;
        seed: number | null;
        steps: number;
        scale: number;
        sampler: string | null;
        model: string | null;
        raw_parameters?: Record<string, any>;
        is_infilling?: boolean;
        notice?: string;
      }>("/image-meta/inspect", {
        image_base64: base64Data,
        filename: file.name,
      });

      const template: BaseTemplate = {
        prompt: inspected.prompt || "",
        negative: inspected.negative_prompt || "",
        seed: inspected.seed ?? Math.floor(Math.random() * 0x1_0000_0000),
        width: inspected.dimensions?.width ?? 1024,
        height: inspected.dimensions?.height ?? 1024,
        steps: inspected.steps ?? 28,
        scale: inspected.scale ?? 5.0,
        sampler: inspected.sampler || "k_euler",
        model: inspected.model || "nai-diffusion-4-5-full",
        raw_parameters: inspected.raw_parameters,
        is_infilling: inspected.is_infilling,
        notice: inspected.notice,
        sourceImage: {
          previewUrl: inspected.source_path
            ? apiUrl(`/results/image?path=${encodeURIComponent(inspected.source_path)}`)
            : base64Data,
          filename: inspected.filename,
          sourcePath: inspected.source_path ?? undefined,
        },
      };

      const resolvedPreview = inspected.source_path
        ? apiUrl(`/results/image?path=${encodeURIComponent(inspected.source_path)}`)
        : base64Data;

      return {
        id,
        file,
        filename: file.name,
        cleanName,
        previewUrl: resolvedPreview,
        template,
        status: "ready",
      };
    } catch (err) {
      return {
        id,
        file,
        filename: file.name,
        cleanName,
        previewUrl: "",
        status: "error",
        error: errorMessage(err),
      };
    }
  }, []);

  const handleFiles = useCallback(
    async (fileList: FileList | File[]) => {
      const validFiles = Array.from(fileList).filter(
        (f) => f.type.startsWith("image/") || f.name.toLowerCase().endsWith(".png"),
      );
      if (validFiles.length === 0) return;

      // Add temporary placeholder items in inspecting state
      const placeholders: ParsedImageItem[] = validFiles.map((f) => ({
        id: `ph_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        file: f,
        filename: f.name,
        cleanName: f.name.replace(/\.[^/.]+$/, ""),
        previewUrl: "",
        status: "inspecting" as const,
      }));

      setItems((prev) => [...prev, ...placeholders]);

      // Inspect all concurrently
      const results = await Promise.all(validFiles.map((f) => inspectSingleFile(f)));

      setItems((prev) => {
        // Replace placeholders with real results
        const placeholderNames = new Set(validFiles.map((f) => f.name));
        const kept = prev.filter((item) => !placeholderNames.has(item.filename));
        return [...kept, ...results];
      });
    },
    [inspectSingleFile],
  );

  const removeItem = useCallback((id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      void handleFiles(e.target.files);
      e.target.value = "";
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDraggingOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      void handleFiles(e.dataTransfer.files);
    }
  };

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDraggingOver(true);
  };

  const onDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDraggingOver(false);
  };

  const handleConfirm = () => {
    const readyItems = items.filter((item) => item.status === "ready" && item.template);
    if (readyItems.length === 0) return;

    onConfirm(
      readyItems.map((item) => ({
        template: item.template!,
        filename: item.filename,
      })),
      autoRun,
    );
    onClose();
  };

  if (!isOpen) return null;

  const inspectingCount = items.filter((item) => item.status === "inspecting").length;
  const readyItems = items.filter((item) => item.status === "ready" && item.template);
  const errorCount = items.filter((item) => item.status === "error").length;
  const totalVariantsPerRound = sourceRound.variants.length;
  const estimatedImagesCount = readyItems.length * totalVariantsPerRound;

  return (
    <div className="batch-derive-overlay" onClick={onClose} role="dialog">
      <div
        aria-label="多图批量派生新批次"
        className="batch-derive-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="batch-derive-header">
          <div className="batch-derive-title-group">
            <h3>
              <GitFork size={18} /> 多图批量派生新批次
            </h3>
            <span className="batch-derive-source-pill">
              源模版批次: <strong>{sourceRound.name}</strong> ({sourceRound.variants.length} 个变体)
            </span>
          </div>
          <button
            aria-label="关闭"
            className="icon-btn"
            onClick={onClose}
            type="button"
          >
            <X size={18} />
          </button>
        </div>

        <div className="batch-derive-body">
          <div
            className={`batch-derive-dropzone ${isDraggingOver ? "drag-over" : ""}`}
            onClick={() => fileInputRef.current?.click()}
            onDragLeave={onDragLeave}
            onDragOver={onDragOver}
            onDrop={onDrop}
          >
            <input
              accept="image/png,image/jpeg,image/webp"
              multiple
              onChange={onFileChange}
              ref={fileInputRef}
              style={{ display: "none" }}
              type="file"
            />
            <div className="dropzone-icon">
              <Upload size={28} />
            </div>
            <div className="dropzone-text">
              <strong>点击多选文件 或 批量拖拽多张图片到此处</strong>
              <p>系统将自动并行解析各自的生成元数据（Prompt、Seed、尺寸、采样器等）作为新批次底模</p>
            </div>
          </div>

          {inspectingCount > 0 ? (
            <div className="batch-derive-status-bar inspecting">
              <Loader2 className="spinning" size={16} />
              <span>正在读取并解析图片元数据中 ({inspectingCount} 张待处理)...</span>
            </div>
          ) : null}

          {errorCount > 0 ? (
            <div className="batch-derive-status-bar error">
              <span>有 {errorCount} 张图片读取或解析失败，已在列表中标出。</span>
            </div>
          ) : null}

          {items.length > 0 ? (
            <div className="batch-derive-list-section">
              <div className="list-section-header">
                <span>
                  已就绪图片 (<strong>{readyItems.length}</strong> / {items.length})
                </span>
                <button
                  className="text-button danger compact"
                  onClick={() => setItems([])}
                  type="button"
                >
                  清空列表
                </button>
              </div>

              <div className="batch-derive-item-list">
                {items.map((item, index) => (
                  <div className={`batch-derive-card status-${item.status}`} key={item.id}>
                    <div className="card-thumb">
                      {item.previewUrl ? (
                        <img alt={item.filename} src={item.previewUrl} />
                      ) : (
                        <FileImage size={24} />
                      )}
                    </div>

                    <div className="card-info">
                      <div className="card-title-row">
                        <span className="card-round-name">
                          第 {index + 1} 批: <strong>{sourceRound.name} - {item.cleanName}</strong>
                        </span>
                        <span className="card-filename" title={item.filename}>
                          {item.filename}
                        </span>
                      </div>

                      {item.status === "ready" && item.template ? (
                        <div className="card-meta-row">
                          <span className="meta-badge">
                            {item.template.width}×{item.template.height}
                          </span>
                          <span className="meta-badge">Seed: {item.template.seed}</span>
                          <span className="meta-badge">{item.template.sampler || "k_euler"}</span>
                          <span className="meta-prompt" title={item.template.prompt}>
                            {item.template.prompt ? item.template.prompt.slice(0, 70) + "..." : "无提示词"}
                          </span>
                        </div>
                      ) : item.status === "inspecting" ? (
                        <div className="card-meta-row inspecting">
                          <Loader2 className="spinning" size={12} />
                          <span>正在解析图片元数据...</span>
                        </div>
                      ) : (
                        <div className="card-meta-row error">
                          <span>{item.error || "解析失败"}</span>
                        </div>
                      )}
                    </div>

                    <button
                      aria-label={`移除 ${item.filename}`}
                      className="icon-btn danger card-remove-btn"
                      onClick={() => removeItem(item.id)}
                      title="移除此图"
                      type="button"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="batch-derive-footer">
          <label className="batch-derive-autorun-label">
            <input
              checked={autoRun}
              onChange={(e) => setAutoRun(e.target.checked)}
              type="checkbox"
            />
            <span>
              创建后立即自动排队出图
              {readyItems.length > 0 ? (
                <strong className="autorun-count-hint">
                  （预计生成 {estimatedImagesCount} 张图片）
                </strong>
              ) : null}
            </span>
          </label>

          <div className="batch-derive-actions">
            <button className="secondary-button" onClick={onClose} type="button">
              取消
            </button>
            <button
              className="primary-button"
              disabled={readyItems.length === 0 || inspectingCount > 0}
              onClick={handleConfirm}
              type="button"
            >
              {autoRun ? <Play size={14} /> : <GitFork size={14} />}
              确定派生 {readyItems.length} 个新批次{autoRun ? " 并开始出图" : ""}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
