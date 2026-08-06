"""GLM Coding Plan API 客户端。

本模块是原 Electron 项目 src/api/usage.js 的 Python 移植版 + 实测修正。

【关键发现（2026-08 实测）】
model-usage 接口的 totalUsage 字段是【时间窗口内用量】，**不是**历史累计：
    1h 窗口 totalTokensUsage=6,977万；25h=2.67亿；168h=21.5亿；720h=74.9亿
故"今日/本周/本月"必须分别用不同时间窗口查询 model-usage。

配额接口 quota/limit 实测只返回 2 个配额：
    TOKENS_LIMIT (5 小时窗口)：仅 Token 用量百分比 + 重置时间
    TIME_LIMIT   (月窗口)   ：MCP 工具调用次数，有 used/total/remaining + 明细

认证方式（与官方 glm-plan-usage 插件、glm-usage-monitor 同源）：
    Authorization 头直接传 Token，**不加 "Bearer " 前缀**。

所有方法为同步实现，由 HA 通过 async_add_executor_job 调用。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .const import (
    API_PATH_MODEL_USAGE,
    API_PATH_TOOL_USAGE,
    API_PATH_QUOTA_LIMIT,
    QUOTA_TYPE_TIME,
    QUOTA_UNIT_MAP,
    WINDOW_MONTH,
    WINDOW_TODAY,
    WINDOW_WEEK,
)

_LOGGER = logging.getLogger(__name__)

_SUPPORTED_HOSTS = re.compile(r"(?:open|dev)\.bigmodel\.cn|^api\.z\.ai")
_CST = timezone(timedelta(hours=8))


class GlmApiError(Exception):
    """GLM API 调用类错误（网络、服务端 5xx、解析失败等）。"""


class GlmAuthError(GlmApiError):
    """认证类错误（401/403，Token 无效）。"""


# ---------------------------------------------------------------------- #
# 工具函数
# ---------------------------------------------------------------------- #
def _http_get(full_url: str, token: str, timeout: int = 20) -> dict[str, Any]:
    """HTTPS GET，返回解析后的 JSON。认证头 Authorization 直接传 token（不带 Bearer）。"""
    try:
        resp = requests.get(
            full_url,
            headers={
                "Authorization": token,
                "Accept-Language": "en-US,en",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
    except requests.exceptions.RequestException as err:
        raise GlmApiError(f"请求失败: {err}") from err

    if resp.status_code in (401, 403):
        raise GlmAuthError(f"认证失败 HTTP {resp.status_code}")
    if resp.status_code != 200:
        raise GlmApiError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        return resp.json()
    except ValueError as err:
        raise GlmApiError(f"响应 JSON 解析失败: {err}") from err


def _describe_window(unit: int | None, number: int | None) -> str:
    """把 unit+number 映射成可读窗口名。"""
    if unit is None or number is None:
        return "未知窗口"
    return f"{number} {QUOTA_UNIT_MAP.get(unit, f'unit{unit}')}"


def _parse_reset_time(raw: Any) -> str | None:
    """解析 nextResetTime 为带时区 ISO 字符串。

    实测该字段返回**毫秒级 Unix 时间戳（int）**，如 1785996842538。
    兼容老格式（字符串 "2025-01-01 00:00:00"）。
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000, tz=_CST).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(raw, str) and raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw) / 1000, tz=_CST).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=_CST).isoformat()
            except ValueError:
                continue
    return None


def _fmt_local(d: datetime) -> str:
    """格式化为接口所需的本地时间字符串。"""
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _query_params(start: datetime, end: datetime) -> str:
    """构造 ?startTime=...&endTime=... 查询串。"""
    from urllib.parse import quote
    return f"?startTime={quote(_fmt_local(start))}&endTime={quote(_fmt_local(end))}"


def _aggregate_daily(x_time: list[str], values: list, label: str) -> dict[str, Any]:
    """把小时级时间序列按天聚合成每日汇总。

    用于在 attributes 里展示历史每日用量。x_time 形如 "2026-08-05 10:00"。
    返回 {"2026-08-05": {label: 123, ...}, ...}
    """
    daily: dict[str, dict[str, Any]] = {}
    for t, v in zip(x_time or [], values or []):
        day = (t.split(" ")[0] if isinstance(t, str) and " " in t else t)
        if day is None:
            continue
        daily.setdefault(day, {})[label] = (daily.get(day, {}).get(label, 0) or 0) + (v or 0)
    return daily


# ---------------------------------------------------------------------- #
# 客户端
# ---------------------------------------------------------------------- #
class GlmCodingPlanClient:
    """GLM Coding Plan 用量查询客户端。"""

    def __init__(self, token: str, base_url: str) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")

        origin_match = re.match(r"(https?://[^/]+)", self.base_url)
        if not origin_match:
            raise GlmApiError(f"非法 base_url: {base_url}")
        self.origin = origin_match.group(1)

        if not _SUPPORTED_HOSTS.search(self.origin):
            raise GlmApiError(f"不支持的端点: {self.origin}")

    def test_connection(self) -> bool:
        """配置校验：打最轻量的 quota/limit 接口，成功即 Token 有效。"""
        _http_get(f"{self.origin}{API_PATH_QUOTA_LIMIT}", self.token)
        return True

    # ---- 单窗口 model-usage 查询 ----
    def _query_model_usage(self, start: datetime, end: datetime) -> dict[str, Any]:
        """查 model-usage，返回 data 部分（含 totalUsage + 时间序列）。"""
        raw = _http_get(
            f"{self.origin}{API_PATH_MODEL_USAGE}{_query_params(start, end)}", self.token
        )
        return raw.get("data") or {} if isinstance(raw, dict) else {}

    def _query_tool_usage(self, start: datetime, end: datetime) -> dict[str, Any]:
        """查 tool-usage，返回 data 部分。"""
        raw = _http_get(
            f"{self.origin}{API_PATH_TOOL_USAGE}{_query_params(start, end)}", self.token
        )
        return raw.get("data") or {} if isinstance(raw, dict) else {}

    def _query_quota_limit(self) -> dict[str, Any]:
        """查 quota/limit（无时间参数），返回 data 部分。"""
        raw = _http_get(f"{self.origin}{API_PATH_QUOTA_LIMIT}", self.token)
        return raw.get("data") or {} if isinstance(raw, dict) else {}

    # ---- 主查询 ----
    def query_usage(self) -> dict[str, Any]:
        """主查询：返回今日/本周/本月三套用量 + 配额。

        实测 totalUsage 是窗口内用量，故按 3 个窗口分别查 model-usage。
        为减少接口调用，今日窗口的明细序列同时用于按天聚合历史。
        """
        if not self.token:
            raise GlmAuthError("未配置 Token")

        now = datetime.now(_CST)

        # 今日：当天 00:00 到现在
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # 本周：最近 7 天
        week_start = now - timedelta(hours=168)
        # 本月：最近 30 天（用最大窗口 720h，足以覆盖月维度 + 按天聚合历史）
        month_start = now - timedelta(hours=720)

        # 并发查 3 个窗口的 model-usage（顺序执行，在 executor 线程中不阻塞事件循环）
        model_today = self._query_model_usage(today_start, now)
        model_week = self._query_model_usage(week_start, now)
        model_month = self._query_model_usage(month_start, now)

        # tool-usage 用月窗口（工具用量次要，单次即可）
        tool = self._query_tool_usage(month_start, now)

        quota = self._query_quota_limit()

        # ---- 规整各窗口用量 ----
        def _extract_total(m: dict[str, Any]) -> dict[str, Any]:
            tu = m.get("totalUsage") or {}
            return {
                "tokens": tu.get("totalTokensUsage", 0),
                "calls": tu.get("totalModelCallCount", 0),
                "by_model": [
                    {"name": mm.get("modelName", ""), "tokens": mm.get("totalTokens", 0)}
                    for mm in (tu.get("modelSummaryList") or [])
                ],
            }

        periods = {
            WINDOW_TODAY: _extract_total(model_today),
            WINDOW_WEEK: _extract_total(model_week),
            WINDOW_MONTH: _extract_total(model_month),
        }

        # ---- 用月窗口的时间序列聚合"历史每日"（覆盖最近 30 天）----
        daily_tokens = _aggregate_daily(
            model_month.get("x_time", []), model_month.get("tokensUsage", []), "tokens"
        )
        daily_calls = _aggregate_daily(
            model_month.get("x_time", []), model_month.get("modelCallCount", []), "calls"
        )
        # 合并 tokens + calls 到同一日期键
        daily_history: list[dict[str, Any]] = []
        for day in sorted(set(daily_tokens) | set(daily_calls)):
            daily_history.append({
                "date": day,
                "tokens": daily_tokens.get(day, {}).get("tokens", 0),
                "calls": daily_calls.get(day, {}).get("calls", 0),
            })

        # ---- 配额 ----
        limits = []
        for lim in (quota.get("limits") or []):
            unit = lim.get("unit")
            number = lim.get("number")
            window = _describe_window(unit, number)
            lim_type = lim.get("type")
            is_time_limit = lim_type == QUOTA_TYPE_TIME
            item: dict[str, Any] = {
                "type": lim_type,
                "window": window,
                "unit": unit,
                "number": number,
                "label": (
                    f"MCP 工具（{window}）" if is_time_limit else f"Token 用量（{window}）"
                ),
                "percentage": lim.get("percentage", 0),
                "next_reset": lim.get("nextResetTime"),
                "next_reset_iso": _parse_reset_time(lim.get("nextResetTime")),
            }
            if is_time_limit:
                item["used"] = lim.get("currentValue")
                item["total"] = lim.get("usage")
                item["remaining"] = lim.get("remaining")
                item["details"] = [
                    {"code": d.get("modelCode"), "usage": d.get("usage")}
                    for d in (lim.get("usageDetails") or [])
                ]
            limits.append(item)

        # ---- 工具用量（月窗口）----
        tool_total = tool.get("totalUsage") or {}

        return {
            "periods": periods,
            "daily_history": daily_history,
            "quota": {
                "level": quota.get("level", "-"),
                "limits": limits,
            },
            "tool_total": {
                "search": tool_total.get("totalNetworkSearchCount", 0),
                "web_read": tool_total.get("totalWebReadMcpCount", 0),
                "zread": tool_total.get("totalZreadMcpCount", 0),
            },
            "fetched_at": datetime.now(_CST).isoformat(),
        }
