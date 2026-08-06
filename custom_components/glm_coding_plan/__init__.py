"""The GLM Coding Plan integration.

架构（与 oil-price 同构）：
- async_setup_entry：创建 GlmCodingPlanClient + DataUpdateCoordinator，存入 hass.data
- coordinator 每 5 分钟拉一次 /api/monitor/usage/* 三个接口
- sensor 平台从 coordinator 拿数据生成实体
- Token 失效（401/403）时触发 reauth，引导用户重新填 Token
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_ENDPOINT, CONF_TOKEN, DOMAIN, ENDPOINTS
from .glm_api import GlmApiError, GlmAuthError, GlmCodingPlanClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# 拉取间隔：配额窗口最短 5 小时，5 分钟粒度足够实时；避免高频请求触发风控。
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=5)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GLM Coding Plan from a config entry."""
    token = entry.data[CONF_TOKEN]
    endpoint_key = entry.data[CONF_ENDPOINT]
    base_url = ENDPOINTS[endpoint_key]["base_url"]

    client = GlmCodingPlanClient(
        token=token,
        base_url=base_url,
    )

    async def async_update_data() -> dict[str, Any]:
        """从 GLM 监控接口拉取并规整数据。"""
        try:
            return await hass.async_add_executor_job(client.query_usage)
        except GlmAuthError as err:
            # 认证失效 → 触发重新认证流程，让用户更新 Token
            _LOGGER.error("GLM Coding Plan Token 失效，触发重新认证: %s", err)
            entry.async_start_reauth_flow(hass)
            raise UpdateFailed(f"认证失败，请重新填写 Token: {err}") from err
        except GlmApiError as err:
            raise UpdateFailed(f"GLM API 调用失败: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"意外错误: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.entry_id}",
        update_method=async_update_data,
        update_interval=DEFAULT_UPDATE_INTERVAL,
        # 首次失败不抛出，保持重试；配置流程已做过校验
        always_update=False,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry（options/数据更新后由 HA 自动调用）。"""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
