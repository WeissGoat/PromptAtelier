import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  GitFork,
  Layers,
  Plus,
  Trash2,
} from "lucide-react";

import { useCompareWorkspace } from "../compare/useCompareWorkspace";
import type { CompareRound } from "../compare/types";

export interface CompareIndexSidebarProps {
  activeRoundId?: string;
  onSelectRound?: (roundId: string) => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

function getRoundStatusTag(round: CompareRound) {
  const hasRunning = round.variants.some((v) => v.status === "running");
  if (hasRunning) {
    return <span className="sidebar-status-tag running">运行中</span>;
  }
  const hasFailed = round.variants.some((v) => v.status === "failed");
  if (hasFailed) {
    return <span className="sidebar-status-tag failed">失败</span>;
  }
  const allSucceeded =
    round.variants.length > 0 && round.variants.every((v) => v.status === "succeeded");
  if (allSucceeded) {
    return <span className="sidebar-status-tag succeeded">已完成</span>;
  }
  return <span className="sidebar-status-tag idle">就绪</span>;
}

export function CompareIndexSidebar({
  activeRoundId,
  onSelectRound,
  isCollapsed = false,
  onToggleCollapse,
}: CompareIndexSidebarProps) {
  const { state, reorderRounds, addNewRound, removeRound } = useCompareWorkspace();

  function handleRoundClick(roundId: string) {
    onSelectRound?.(roundId);
    const element = document.getElementById(`round-section-${roundId}`);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function handleDerive(roundId: string) {
    const newRoundId = addNewRound(roundId);
    onSelectRound?.(newRoundId);
    setTimeout(() => {
      const element = document.getElementById(`round-section-${newRoundId}`);
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, 60);
  }

  function handleAddNewRoundBottom() {
    const newRoundId = addNewRound();
    onSelectRound?.(newRoundId);
    setTimeout(() => {
      const element = document.getElementById(`round-section-${newRoundId}`);
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, 60);
  }

  if (isCollapsed) {
    return (
      <aside
        aria-label="批次导航"
        className="compare-rounds-sidebar collapsed"
        data-testid="compare-index-sidebar"
      >
        <div className="sidebar-collapsed-header">
          <button
            className="sidebar-collapse-toggle-btn"
            onClick={onToggleCollapse}
            title="展开批次索引"
            type="button"
          >
            <ChevronRight size={14} />
          </button>
        </div>

        <div className="sidebar-collapsed-strip">
          {state.rounds.map((round, index) => {
            const isActive = activeRoundId === round.id;
            return (
              <button
                className={`sidebar-collapsed-node ${isActive ? "active" : ""}`}
                key={round.id}
                onClick={() => handleRoundClick(round.id)}
                title={`${round.name} (${round.variants.length}个变体)`}
                type="button"
              >
                #{index + 1}
              </button>
            );
          })}
        </div>

        <div className="sidebar-collapsed-footer">
          <button
            className="sidebar-collapsed-add-btn"
            onClick={handleAddNewRoundBottom}
            title="在底部新增批次"
            type="button"
          >
            <Plus size={14} />
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside
      aria-label="批次导航"
      className="compare-rounds-sidebar"
      data-testid="compare-index-sidebar"
    >
      <div className="sidebar-header">
        <div className="sidebar-title-wrap">
          <Layers className="sidebar-title-icon" size={15} />
          <span className="sidebar-title-text">批次索引</span>
          <span className="sidebar-count-badge">{state.rounds.length} 批</span>
        </div>

        <div className="sidebar-header-actions">
          {onToggleCollapse ? (
            <button
              className="sidebar-collapse-toggle-btn"
              onClick={onToggleCollapse}
              title="折叠批次索引"
              type="button"
            >
              <ChevronLeft size={14} />
            </button>
          ) : null}
        </div>
      </div>

      <nav className="sidebar-rounds-list">
        {state.rounds.map((round, index) => {
          const isActive = activeRoundId === round.id;
          return (
            <div
              className={`sidebar-round-item ${isActive ? "active" : ""}`}
              data-testid={`sidebar-round-item-${round.id}`}
              key={round.id}
              onClick={() => handleRoundClick(round.id)}
            >
              <div className="sidebar-item-header">
                <span className="sidebar-item-order">#{index + 1}</span>
                <span className="sidebar-round-name" title={round.name}>
                  {round.name}
                </span>
                <span className="sidebar-variants-count">
                  {round.variants.length} 变体
                </span>
              </div>

              <div className="sidebar-item-meta">
                {getRoundStatusTag(round)}
                <span
                  className="sidebar-prompt-preview"
                  title={round.basePrompt || round.template?.prompt}
                >
                  {round.basePrompt || round.template?.prompt
                    ? (round.basePrompt || round.template?.prompt).slice(0, 24) +
                      ((round.basePrompt || round.template?.prompt).length > 24 ? "..." : "")
                    : "默认提示词"}
                </span>
              </div>

              <div
                className="sidebar-item-actions"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="sidebar-actions-group">
                  <button
                    aria-label="上移批次"
                    className="sidebar-action-btn"
                    data-testid={`sidebar-round-up-${round.id}`}
                    disabled={index === 0}
                    onClick={() => reorderRounds(index, index - 1)}
                    title="上移批次"
                    type="button"
                  >
                    <ArrowUp size={12} />
                  </button>
                  <button
                    aria-label="下移批次"
                    className="sidebar-action-btn"
                    data-testid={`sidebar-round-down-${round.id}`}
                    disabled={index === state.rounds.length - 1}
                    onClick={() => reorderRounds(index, index + 1)}
                    title="下移批次"
                    type="button"
                  >
                    <ArrowDown size={12} />
                  </button>
                </div>

                <div className="sidebar-actions-group right">
                  <button
                    aria-label="向下派生"
                    className="sidebar-action-btn derive-btn"
                    data-testid={`sidebar-round-derive-${round.id}`}
                    onClick={() => handleDerive(round.id)}
                    title="以此批变体与diff为模板，在下方派生新批次"
                    type="button"
                  >
                    <GitFork size={12} />
                    <span>向下派生</span>
                  </button>

                  {state.rounds.length > 1 ? (
                    <button
                      aria-label="删除批次"
                      className="sidebar-action-btn danger-btn"
                      data-testid={`sidebar-round-delete-${round.id}`}
                      onClick={() => removeRound(round.id)}
                      title="删除此批"
                      type="button"
                    >
                      <Trash2 size={12} />
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <button
          className="sidebar-add-bottom-btn"
          onClick={handleAddNewRoundBottom}
          type="button"
        >
          <Plus size={13} />
          <span>在末尾新增批次</span>
        </button>
      </div>
    </aside>
  );
}
