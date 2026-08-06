"""Config flow for GLM Coding Plan integration.

可视化配置流程：
1. 用户在「集成」里点添加 → 弹出表单
2. 填入 Token（GLM Coding Plan 的 API Key）+ 选择端点 + 自定义名称
3. 提交前用 Token 实际打一次监控接口做校验
4. 通过 → 创建配置项
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import CONF_ENDPOINT, CONF_NAME, CONF_TOKEN, DEFAULT_ENDPOINT, DOMAIN, ENDPOINTS
from .glm_api import GlmCodingPlanClient, GlmApiError, GlmAuthError

_LOGGER = logging.getLogger(__name__)


def _token_fingerprint(token: str) -> str:
    """对 Token 摘前 8 位做指纹（避免明文 Token 写进 unique_id）。

    用 SHA-256 前 16 个十六进制字符，既保证唯一性又不泄露原始 Token。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _build_user_schema(defaults: dict[str, Any] | None = None, mask_token: bool = True) -> vol.Schema:
    """构建设置表单的 schema。

    mask_token=True（首次/重认证）：密码掩码输入框
    mask_token=False（options 流）：提示"留空保留原值"，不回显旧 token
    """
    d = defaults or {}
    schema: dict = {
        vol.Required(
            CONF_NAME,
            description={"suggested_value": d.get(CONF_NAME, "GLM Coding Plan")},
        ): str,
    }
    if mask_token:
        # 首次配置：密码掩码
        schema[vol.Required(CONF_TOKEN)] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    else:
        # options 流：留空保留原值，不清空存储
        schema[vol.Optional(CONF_TOKEN)] = TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD,
                # 不设 suggested_value → 输入框为空，避免把明文 token 暴露在 DOM 里
            )
        )
    schema[vol.Required(
        CONF_ENDPOINT, default=d.get(CONF_ENDPOINT, DEFAULT_ENDPOINT)
    )] = vol.In({k: v["label"] for k, v in ENDPOINTS.items()})
    return vol.Schema(schema)


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """校验用户输入。

    用 Token 实际打一次监控接口（quota/limit 不依赖时间窗口，最轻量），
    成功即认为 Token 有效。
    """
    token = data[CONF_TOKEN].strip()
    endpoint = data[CONF_ENDPOINT]
    base_url = ENDPOINTS[endpoint]["base_url"]

    if not token:
        raise GlmAuthError("Token 不能为空")

    client = GlmCodingPlanClient(token=token, base_url=base_url)
    # 在 executor 里跑，避免阻塞事件循环
    await hass.async_add_executor_job(client.test_connection)

    return {"title": data[CONF_NAME]}


class GlmCodingPlanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GLM Coding Plan."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """首次添加集成的表单步骤。"""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _validate_input(self.hass, user_input)
            except GlmAuthError:
                errors["base"] = "invalid_auth"
            except GlmApiError as err:
                _LOGGER.warning("GLM Coding Plan 连接校验失败: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("GLM Coding Plan 配置流程出现意外错误")
                errors["base"] = "unknown"
            else:
                # 用 Token 的 SHA-256 指纹做唯一性校验（不把明文 token 写进 unique_id）
                token = user_input[CONF_TOKEN].strip()
                await self.async_set_unique_id(f"glm_cp_{_token_fingerprint(token)}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_TOKEN: token,
                        CONF_ENDPOINT: user_input[CONF_ENDPOINT],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_user_schema(),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any] | None = None
    ) -> FlowResult:
        """Token 失效时触发的重新认证流程。"""
        if entry_data is None:
            # HA ≥ 2024.8 传入 ConfigEntry 而非 dict；兼容处理
            entry = self._get_reauth_entry()
            entry_data = entry.data
        self._reauth_data = entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """重新输入 Token 的确认步骤。"""
        errors: dict[str, str] = {}
        existing = self._reauth_data
        entry = self._get_reauth_entry()

        if user_input is not None:
            new_data = {
                CONF_NAME: existing.get(CONF_NAME, entry.title),
                CONF_TOKEN: user_input[CONF_TOKEN].strip(),
                CONF_ENDPOINT: existing.get(CONF_ENDPOINT, DEFAULT_ENDPOINT),
            }
            try:
                await _validate_input(self.hass, new_data)
            except GlmAuthError:
                errors["base"] = "invalid_auth"
            except GlmApiError as err:
                _LOGGER.warning("GLM Coding Plan 重新认证失败: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("GLM Coding Plan 重新认证意外错误")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_success")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            description_placeholders={"name": existing.get(CONF_NAME, entry.title)},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "GlmCodingPlanOptionsFlow":
        """支持「配置」按钮里修改 Token / 端点。"""
        return GlmCodingPlanOptionsFlow(config_entry)


class GlmCodingPlanOptionsFlow(config_entries.OptionsFlow):
    """Options flow：允许随时修改 Token / 端点 / 名称。"""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Init options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Options 主步骤。"""
        errors: dict[str, str] = {}
        entry = self.config_entry
        current = {**entry.data}

        if user_input is not None:
            new_data = {
                CONF_NAME: user_input.get(CONF_NAME, current.get(CONF_NAME)),
                # Token 留空则保留原值（与 glm-usage-monitor 同思路：绝不清空）
                CONF_TOKEN: user_input.get(CONF_TOKEN) or current.get(CONF_TOKEN, ""),
                CONF_ENDPOINT: user_input.get(CONF_ENDPOINT, current.get(CONF_ENDPOINT)),
            }
            try:
                await _validate_input(self.hass, new_data)
            except GlmAuthError:
                errors["base"] = "invalid_auth"
            except GlmApiError as err:
                _LOGGER.warning("GLM Coding Plan options 校验失败: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("GLM Coding Plan options 意外错误")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data=new_data, title=new_data[CONF_NAME]
                )
                return self.async_create_entry(title=new_data[CONF_NAME], data={})

        return self.async_show_form(
            step_id="init",
            # options 流：mask_token=False → Token 输入框留空保留原值，不回显明文
            data_schema=_build_user_schema(current, mask_token=False),
            errors=errors,
        )
