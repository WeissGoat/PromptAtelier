from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field
import requests

from tags_machine_core.clients.novelai import IMAGE_BASE_URL, NOVELAI_WEB_HEADERS

TIER_NAMES = {
    0: "None",
    1: "Tablet",
    2: "Scroll",
    3: "Opus",
}


def mask_token(token: str | None) -> str:
    """对 Token 进行脱敏处理。"""
    if not token:
        return ""
    text = str(token).strip()
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


class NovelAIUsageInfo(BaseModel):
    configured: bool = True
    token_masked: str = ""
    active: bool = False
    tier: int = 0
    tier_name: str = "None"
    anlas: int = 0
    fixed_anlas: int = 0
    purchased_anlas: int = 0
    usage_percent: float = 0.0
    time_until_next_percent: float = 0.0
    unlimited_v5_eligible: bool = False
    error: str | None = None


def inquire_novelai_usage(
    access_token: str | None,
    base_url: str = IMAGE_BASE_URL,
    session: Any | None = None,
    timeout: float = 15.0,
) -> NovelAIUsageInfo:
    """查询 NovelAI 会员订阅与 V5 用量快照。"""
    if not access_token:
        return NovelAIUsageInfo(
            configured=False,
            error="未配置 NovelAI Token (请检查 config 或 NAI_ACCESS_TOKEN 环境变量)",
        )

    masked = mask_token(access_token)
    url = f"{base_url.rstrip('/')}/user/subscription"
    headers = {
        **NOVELAI_WEB_HEADERS,
        # 官网查订阅时也带这个头；不带 correlation id
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token.strip()}",
    }

    client = session or requests

    try:
        response = client.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            active = bool(data.get("active", False))
            tier = int(data.get("tier", 0))
            tier_name = TIER_NAMES.get(tier, f"Tier {tier}")

            training_steps = data.get("trainingStepsLeft") or {}
            fixed_anlas = int(training_steps.get("fixedTrainingStepsLeft") or 0)
            purchased_anlas = int(training_steps.get("purchasedTrainingSteps") or 0)
            anlas = fixed_anlas if fixed_anlas > 0 else purchased_anlas

            usage = data.get("usage") or {}
            usage_percent = float(usage.get("percent") or 0.0)
            time_until_next = float(usage.get("timeUntilNextPercent") or 0.0)

            # Opus 订阅拥有特定免费出图额度，且 V5 拥有会员用量池
            unlimited_v5_eligible = active and tier >= 3

            return NovelAIUsageInfo(
                configured=True,
                token_masked=masked,
                active=active,
                tier=tier,
                tier_name=tier_name,
                anlas=anlas,
                fixed_anlas=fixed_anlas,
                purchased_anlas=purchased_anlas,
                usage_percent=usage_percent,
                time_until_next_percent=time_until_next,
                unlimited_v5_eligible=unlimited_v5_eligible,
                error=None,
            )
        elif response.status_code in (401, 403):
            return NovelAIUsageInfo(
                configured=True,
                token_masked=masked,
                error=f"Token 无效或已过期 (HTTP {response.status_code})",
            )
        else:
            return NovelAIUsageInfo(
                configured=True,
                token_masked=masked,
                error=f"NovelAI 请求失败 (HTTP {response.status_code}): {response.text[:120]}",
            )
    except Exception as exc:
        return NovelAIUsageInfo(
            configured=True,
            token_masked=masked,
            error=f"连接失败: {exc}",
        )


def format_usage_summary(info: NovelAIUsageInfo) -> str:
    """格式化为终端易读的监控看板文本。"""
    if not info.configured:
        return "⚠️ 未配置 NovelAI Token。"
    if info.error:
        return f"❌ 查询失败 ({info.token_masked}): {info.error}"

    status_str = "有效" if info.active else "无效/未激活"
    tier_str = f"{info.tier_name} (Tier {info.tier})" if info.tier else "无订阅"
    
    # 绘制进度条 [##########----------] 50%
    bar_width = 20
    filled = int(round(info.usage_percent / 100.0 * bar_width))
    bar = "#" * filled + "-" * (bar_width - filled)
    
    countdown_str = "已满" if info.usage_percent >= 100.0 else f"{info.time_until_next_percent:.1f} 秒"

    lines = [
        "================================================",
        "          NovelAI 会员与 V5 用量监控",
        "================================================",
        f"  Token:              {info.token_masked}",
        f"  会员状态:            {status_str} · {tier_str}",
        f"  Anlas 点数:         {info.anlas:,} (固定: {info.fixed_anlas:,} / 购买: {info.purchased_anlas:,})",
        f"  V5 会员用量:        {info.usage_percent:.1f}% [{bar}]",
        f"  下次恢复 1%:         {countdown_str}",
        f"  V5 免点额度状态:     {'充足 (免费额度可用)' if info.usage_percent > 0 else '已耗尽 (继续生成将消耗点数)'}",
        "================================================",
    ]
    return "\n".join(lines)
