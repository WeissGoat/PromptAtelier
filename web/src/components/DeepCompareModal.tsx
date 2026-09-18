import {
  Columns,
  Maximize2,
  Minimize2,
  MoveHorizontal,
  RotateCcw,
  Sparkles,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type MouseEvent, type WheelEvent } from "react";

import type { PromptVariant } from "../compare/types";

type DeepCompareModalProps = {
  isOpen: boolean;
  leftVariant: PromptVariant | null;
  rightVariant: PromptVariant | null;
  onClose: () => void;
};

export function DeepCompareModal({
  isOpen,
  leftVariant,
  rightVariant,
  onClose,
}: DeepCompareModalProps) {
  const [mode, setMode] = useState<"split" | "flicker">("split");
  const [sliderPos, setSliderPos] = useState(50); // percentage 0 to 100
  const [isDragging, setIsDragging] = useState(false);
  const [activeFlicker, setActiveFlicker] = useState<"left" | "right">("left");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const panStartRef = useRef({ x: 0, y: 0 });
  const stageRef = useRef<HTMLDivElement | null>(null);

  const leftUrl = leftVariant?.resultImage?.url;
  const rightUrl = rightVariant?.resultImage?.url;

  // Keyboard navigation for flicker mode and Escape to close
  useEffect(() => {
    if (!isOpen) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        setActiveFlicker((prev) => (prev === "left" ? "right" : "left"));
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  // Window-level mouse movement for ultra-smooth slider dragging and panning
  useEffect(() => {
    if (!isDragging && !isPanning) return;

    function handleWindowMouseMove(e: globalThis.MouseEvent) {
      if (isDragging && stageRef.current) {
        const rect = stageRef.current.getBoundingClientRect();
        const offsetX = e.clientX - rect.left;
        const percent = Math.min(100, Math.max(0, (offsetX / rect.width) * 100));
        setSliderPos(percent);
      } else if (isPanning) {
        const dx = e.clientX - panStartRef.current.x;
        const dy = e.clientY - panStartRef.current.y;
        setPan((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
        panStartRef.current = { x: e.clientX, y: e.clientY };
      }
    }

    function handleWindowMouseUp() {
      setIsDragging(false);
      setIsPanning(false);
    }

    window.addEventListener("mousemove", handleWindowMouseMove);
    window.addEventListener("mouseup", handleWindowMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleWindowMouseMove);
      window.removeEventListener("mouseup", handleWindowMouseUp);
    };
  }, [isDragging, isPanning]);

  const handleStageMouseDown = useCallback((e: MouseEvent<HTMLDivElement>) => {
    if (e.button === 0 && stageRef.current) {
      const rect = stageRef.current.getBoundingClientRect();
      const offsetX = e.clientX - rect.left;
      const percent = Math.min(100, Math.max(0, (offsetX / rect.width) * 100));
      setSliderPos(percent);
      setIsDragging(true);
    }
  }, []);

  const handleCanvasMouseDown = useCallback((e: MouseEvent<HTMLDivElement>) => {
    if (
      e.button === 1 ||
      e.button === 2 ||
      (e.button === 0 && e.altKey) ||
      (e.button === 0 && e.target === e.currentTarget)
    ) {
      e.preventDefault();
      setIsPanning(true);
      panStartRef.current = { x: e.clientX, y: e.clientY };
    }
  }, []);

  const handleWheel = useCallback((e: WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.15 : -0.15;
    setZoom((z) => Math.min(4, Math.max(0.25, Math.round((z + delta) * 100) / 100)));
  }, []);

  function handleResetView() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSliderPos(50);
  }

  if (!isOpen || !leftVariant || !rightVariant || !leftUrl || !rightUrl) {
    return null;
  }

  return (
    <div className="deep-compare-backdrop">
      <div className={`deep-compare-dialog ${isFullscreen ? "fullscreen" : ""}`}>
        <div className="deep-compare-header">
          <div className="dialog-title-group">
            <h3>深度视觉对比 (Deep Compare)</h3>
            <span className="compare-pair-hint">
              <strong>{leftVariant.name}</strong> vs <strong>{rightVariant.name}</strong>
            </span>
          </div>

          <div className="dialog-mode-controls">
            <div className="segmented-control">
              <button
                className={mode === "split" ? "active" : ""}
                onClick={() => setMode("split")}
                type="button"
              >
                <Columns size={14} /> 卷帘对比 (Split Slider)
              </button>
              <button
                className={mode === "flicker" ? "active" : ""}
                onClick={() => setMode("flicker")}
                type="button"
              >
                <Sparkles size={14} /> 瞬切闪烁 (Flicker Mode)
              </button>
            </div>

            <div className="zoom-controls">
              <button
                onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
                title="缩小 (亦可滚轮缩放)"
                type="button"
              >
                <ZoomOut size={14} />
              </button>
              <span>{Math.round(zoom * 100)}%</span>
              <button
                onClick={() => setZoom((z) => Math.min(4, z + 0.25))}
                title="放大 (亦可滚轮缩放)"
                type="button"
              >
                <ZoomIn size={14} />
              </button>
              <button onClick={handleResetView} title="重置缩放与平移" type="button">
                <RotateCcw size={14} />
              </button>
              <button
                onClick={() => setIsFullscreen((prev) => !prev)}
                title={isFullscreen ? "退出全屏" : "全屏查看"}
                type="button"
              >
                {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              </button>
            </div>

            <button className="close-btn" onClick={onClose} title="关闭对比" type="button">
              <X size={18} />
            </button>
          </div>
        </div>

        <div
          className={`deep-compare-canvas-area ${mode}`}
          onContextMenu={(e) => e.preventDefault()}
          onMouseDown={handleCanvasMouseDown}
          onWheel={handleWheel}
        >
          {mode === "split" ? (
            <div
              className="split-slider-stage"
              onMouseDown={handleStageMouseDown}
              ref={stageRef}
              style={{
                transform: `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)`,
                transformOrigin: "center center",
              }}
            >
              {/* Underlying Left image: sizes the entire stage perfectly */}
              <img
                alt={leftVariant.name}
                className="split-stage-img left-img"
                draggable={false}
                src={leftUrl}
              />
              <span className="image-layer-label left">左: {leftVariant.name}</span>

              {/* Clipped Right image on top: guaranteed identical bounding box */}
              <div
                className="split-overlay-container"
                style={{
                  clipPath: `inset(0 0 0 ${sliderPos}%)`,
                }}
              >
                <img
                  alt={rightVariant.name}
                  className="split-stage-img right-img"
                  draggable={false}
                  src={rightUrl}
                />
                <span className="image-layer-label right">右: {rightVariant.name}</span>
              </div>

              {/* Draggable Divider Handle */}
              <div
                className="split-slider-handle"
                onMouseDown={(e) => {
                  e.stopPropagation();
                  setIsDragging(true);
                }}
                style={{ left: `${sliderPos}%` }}
              >
                <div className="slider-handle-line" />
                <div className="slider-handle-grabber">
                  <MoveHorizontal size={14} />
                </div>
              </div>
            </div>
          ) : (
            <div
              className="flicker-container"
              onClick={() => setActiveFlicker((prev) => (prev === "left" ? "right" : "left"))}
              style={{
                transform: `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)`,
                transformOrigin: "center center",
              }}
            >
              <img
                alt={activeFlicker === "left" ? leftVariant.name : rightVariant.name}
                className="flicker-image"
                draggable={false}
                src={activeFlicker === "left" ? leftUrl : rightUrl}
              />
              <div className="flicker-indicator-bar">
                <span className={`flicker-badge ${activeFlicker === "left" ? "active" : ""}`}>
                  A: {leftVariant.name}
                </span>
                <span className={`flicker-badge ${activeFlicker === "right" ? "active" : ""}`}>
                  B: {rightVariant.name}
                </span>
                <span className="flicker-shortcut-hint">按 ← / → 键或空格键快速切换</span>
              </div>
            </div>
          )}
        </div>

        <div className="deep-compare-footer">
          <div className="diff-comparison-summary">
            <div className="variant-summary-col">
              <strong>{leftVariant.name}:</strong>
              <span>
                {leftVariant.diff.added.map((t, i) => (
                  <span className="diff-pill added" key={i}>
                    +{t}
                  </span>
                ))}
              </span>
            </div>
            <div className="variant-summary-col">
              <strong>{rightVariant.name}:</strong>
              <span>
                {rightVariant.diff.added.map((t, i) => (
                  <span className="diff-pill added" key={i}>
                    +{t}
                  </span>
                ))}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
