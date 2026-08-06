"""Support for GLM Coding Plan sensors.

传感器设计（基于 2026-08 实测真实接口口径）：
- period_tokens : 今日/本周/本月 Token 用量（来自 model-usage 各时间窗口）
- period_calls  : 今日/本周/本月 模型调用次数
- quota_tokens  : 5 小时 Token 用量百分比（TOKENS_LIMIT）
- quota_time    : 月度 MCP 工具调用次数配额（TIME_LIMIT，有 used/total/remaining）
- plan_level    : 套餐等级

历史每日数据作为 Token 用量传感器的 extra_state_attributes。
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SENSOR_TYPES, WINDOW_LABELS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GLM Coding Plan sensors from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = data["coordinator"]
    entry_name = config_entry.data.get("name", "GLM Coding Plan")

    entities: list[GlmSensor] = []
    for sensor_key, sensor_def in SENSOR_TYPES.items():
        entities.append(
            GlmSensor(
                coordinator=coordinator,
                config_entry=config_entry,
                entry_name=entry_name,
                sensor_key=sensor_key,
                sensor_def=sensor_def,
            )
        )

    async_add_entities(entities)


def _to_int(value: Any) -> int | None:
    """安全转整数，失败返回 None。所有用量/配额均为整数。"""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _remaining_pct(used_pct: Any) -> int | None:
    """把"已用百分比"换算为"剩余百分比"。如 used=12 → remaining=88。"""
    n = _to_int(used_pct)
    if n is None:
        return None
    return max(0, 100 - n)


class GlmSensor(CoordinatorEntity, SensorEntity):
    """Representation of a GLM Coding Plan sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        config_entry: ConfigEntry,
        entry_name: str,
        sensor_key: str,
        sensor_def: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._sensor_key = sensor_key
        self._sensor_def = sensor_def
        self._kind = sensor_def["kind"]
        self._window = sensor_def.get("window")

        self._attr_unique_id = f"{config_entry.entry_id}_{sensor_key}"
        self._attr_name = sensor_def["name"]
        self._attr_icon = sensor_def.get("icon")

        # 用量类用 TOTAL_INCREASING；配额百分比用 MEASUREMENT；等级/文本不设
        if self._kind in ("period_tokens", "period_calls"):
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        elif self._kind in ("quota_tokens", "quota_time"):
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = "%"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=entry_name,
            manufacturer="智谱 AI / Z.ai",
            model="GLM Coding Plan",
            entry_type="service",
            configuration_url="https://open.bigmodel.cn/",
            sw_version="1.0",
        )

    # ------------------------------------------------------------------ #
    # 数据提取
    # ------------------------------------------------------------------ #
    def _find_quota_limit(self) -> dict[str, Any] | None:
        """根据 (match_type, match_unit) 在 quota.limits 里找对应配额。"""
        data = self.coordinator.data
        if not data:
            return None
        match_type = self._sensor_def.get("match_type")
        match_unit = self._sensor_def.get("match_unit")
        for lim in data.get("quota", {}).get("limits", []):
            if lim.get("type") == match_type and lim.get("unit") == match_unit:
                return lim
        return None

    def _build_daily_attrs(self) -> dict[str, Any]:
        """构建历史每日 attributes（Token 用量传感器专用）。

        把 daily_history 列表转成 {"2026-08-05": 123, ...} 形式，
        HA 里可在属性面板看到最近 30 天每天的用量。
        """
        data = self.coordinator.data
        if not data:
            return {}
        daily = data.get("daily_history") or []
        return {item["date"]: item["tokens"] for item in daily if item.get("date")}

    def _get_state_and_attrs(self) -> tuple[StateType, dict[str, Any] | None]:
        """根据 kind 计算 state 与 extra_state_attributes。"""
        data = self.coordinator.data
        if not data:
            return None, None

        # —— 今日/本周/本月 Token 用量 ——
        if self._kind == "period_tokens":
            period = data.get("periods", {}).get(self._window, {})
            attrs: dict[str, Any] = {
                "period": WINDOW_LABELS.get(self._window, self._window),
                "by_model": period.get("by_model", []),
            }
            # 历史每日用量（最近 30 天）—— 作为 attributes 呈现
            attrs["daily_history"] = self._build_daily_attrs()
            return _to_int(period.get("tokens")), attrs

        # —— 今日/本周/本月 调用次数 ——
        if self._kind == "period_calls":
            period = data.get("periods", {}).get(self._window, {})
            attrs = {"period": WINDOW_LABELS.get(self._window, self._window)}
            return _to_int(period.get("calls")), attrs

        # —— Token 剩余配额百分比（TOKENS_LIMIT，5 小时窗口）——
        # 接口返回的是"已用百分比"，state 换算为"剩余百分比"，更直观
        if self._kind == "quota_tokens":
            lim = self._find_quota_limit()
            if not lim:
                return None, None
            attrs = {
                "used_percent": _to_int(lim.get("percentage")),
                "window": lim.get("window"),
                "label": lim.get("label"),
                "next_reset": lim.get("next_reset"),
            }
            if lim.get("next_reset_iso"):
                attrs["next_reset_time"] = lim["next_reset_iso"]
            return _remaining_pct(lim.get("percentage")), attrs

        # —— MCP 工具剩余配额百分比（TIME_LIMIT，月窗口）——
        if self._kind == "quota_time":
            lim = self._find_quota_limit()
            if not lim:
                return None, None
            attrs = {
                "used": _to_int(lim.get("used")),
                "total": _to_int(lim.get("total")),
                "remaining": _to_int(lim.get("remaining")),
                "used_percent": _to_int(lim.get("percentage")),
                "window": lim.get("window"),
                "label": lim.get("label"),
                "next_reset": lim.get("next_reset"),
            }
            if lim.get("next_reset_iso"):
                attrs["next_reset_time"] = lim["next_reset_iso"]
            if lim.get("details"):
                attrs["usage_details"] = lim["details"]
            return _remaining_pct(lim.get("percentage")), attrs

        # —— 套餐等级 ——
        if self._kind == "plan_level":
            level = data.get("quota", {}).get("level", "-")
            return str(level), None

        return None, None

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        state, _ = self._get_state_and_attrs()
        return state

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        _, attrs = self._get_state_and_attrs()
        if attrs is None:
            return None
        data = self.coordinator.data
        if data and data.get("fetched_at"):
            attrs["fetched_at"] = data["fetched_at"]
        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None
