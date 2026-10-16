import { AlertCircle, CheckCircle2, ChevronUp, Loader2, RefreshCw, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { errorMessage, getNovelAIUsage, refreshNovelAIUsage } from "../api/client";
import type { NovelAIUsageInfo } from "../api/types";

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "已满";
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `约 ${Math.round(seconds / 60)} 分钟`;
  return `约 ${(seconds / 3600).toFixed(1)} 小时`;
}

function formatAnlasShort(anlas: number): string {
  if (anlas >= 10000) return `${(anlas / 1000).toFixed(1)}k`;
  if (anlas >= 1000) return `${(anlas / 1000).toFixed(1)}k`;
  return anlas.toLocaleString();
}

function usageTone(percent: number, active: boolean): "ok" | "warn" | "danger" {
  if (!active || percent <= 0) return "danger";
  if (percent <= 25) return "warn";
  return "ok";
}

export function NovelAIUsageBadge() {
  const [data, setData] = useState<NovelAIUsageInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [open, setOpen] = useState(false);
  const [actionError, setActionError] = useState("");
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let unmounted = false;
    getNovelAIUsage()
      .then((res) => {
        if (!unmounted) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!unmounted) {
          setData({
            configured: true,
            token_masked: "",
            active: false,
            tier: 0,
            tier_name: "Error",
            anlas: 0,
            fixed_anlas: 0,
            purchased_anlas: 0,
            usage_percent: 0,
            time_until_next_percent: 0,
            unlimited_v5_eligible: false,
            error: errorMessage(err),
          });
          setLoading(false);
        }
      });

    return () => {
      unmounted = true;
    };
  }, []);

  // 点击外部关闭弹层
  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const handleRefresh = async (e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (refreshing) return;
    setRefreshing(true);
    setActionError("");
    try {
      const refreshed = await refreshNovelAIUsage();
      setData(refreshed);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) {
    return (
      <div className="novelai-usage-bar loading">
        <Loader2 className="spin" size={14} />
        <span>NovelAI 查询中...</span>
      </div>
    );
  }

  if (!data?.configured) {
    return (
      <div className="novelai-usage-bar unconfigured" title="未配置 NovelAI Access Token">
        <AlertCircle size={14} />
        <span>NAI: 未配置 Token</span>
      </div>
    );
  }

  const tone = usageTone(data.usage_percent, data.active);

  return (
    <div className="novelai-usage-wrapper" ref={popoverRef}>
      <button
        aria-label="NovelAI 会员与 V5 用量"
        className={`novelai-usage-bar active ${tone}`}
        onClick={() => setOpen((prev) => !prev)}
        title="NovelAI 会员与 V5 用量 (点击查看详情)"
        type="button"
      >
        <Sparkles className="sparkle-icon" size={15} />
        <span className="badge-text">
          V5 {data.usage_percent.toFixed(1)}% · {formatAnlasShort(data.anlas)}
        </span>
        <ChevronUp className={open ? "chevron open" : "chevron"} size={14} />
      </button>

      {open ? (
        <div className="novelai-usage-popover">
          <div className="popover-header">
            <div className="header-title">
              <Sparkles size={16} />
              <strong>NovelAI 会员与 V5 用量</strong>
            </div>
            <button className="close-btn" onClick={() => setOpen(false)} title="关闭" type="button">
              <X size={14} />
            </button>
          </div>

          {actionError ? <div className="popover-alert error">{actionError}</div> : null}
          {data.error ? <div className="popover-alert error">{data.error}</div> : null}

          <div className="usage-details-grid">
            <div className="detail-item">
              <span className="label">会员档位</span>
              <span className="value">
                {data.tier_name} (Tier {data.tier})
              </span>
            </div>
            <div className="detail-item">
              <span className="label">会员状态</span>
              <span className={`value status-tag ${data.active ? "ok" : "warn"}`}>
                {data.active ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                {data.active ? "有效" : "未激活 / 无效"}
              </span>
            </div>
            <div className="detail-item">
              <span className="label">Anlas 点数</span>
              <span className="value">{data.anlas.toLocaleString()}</span>
            </div>
            <div className="detail-item">
              <span className="label">点数构成</span>
              <span className="sub-value">
                固定: {data.fixed_anlas.toLocaleString()} / 购买: {data.purchased_anlas.toLocaleString()}
              </span>
            </div>
            <div className="detail-item full-width">
              <div className="usage-progress-header">
                <span className="label">V5 会员额度</span>
                <span className={`percent-num ${tone}`}>{data.usage_percent.toFixed(1)}%</span>
              </div>
              <div className="usage-progress-track">
                <div
                  className={`usage-progress-fill ${tone}`}
                  style={{ width: `${Math.min(100, Math.max(0, data.usage_percent))}%` }}
                />
              </div>
            </div>
            <div className="detail-item">
              <span className="label">下次恢复 1%</span>
              <span className="value">{formatCountdown(data.time_until_next_percent)}</span>
            </div>
            <div className="detail-item">
              <span className="label">Token</span>
              <span className="value font-mono">{data.token_masked || "--"}</span>
            </div>
          </div>

          <div className="popover-footer">
            <span className="status-note">
              {data.usage_percent > 0 ? "🟢 V5 免费额度可用" : "🔴 V5 额度已尽，出图将耗点"}
            </span>
            <button
              className="refresh-button"
              disabled={refreshing}
              onClick={handleRefresh}
              type="button"
            >
              <RefreshCw className={refreshing ? "spin" : ""} size={13} />
              {refreshing ? "刷新中…" : "刷新"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
