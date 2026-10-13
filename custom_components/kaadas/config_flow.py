"""配置流程：填 token 和 uid，自动列出账号下的门锁。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .api import KaadasApi, KaadasAuthError, KaadasError
from .const import (
    CONF_IMAGE_ROTATION,
    CONF_INFO_INTERVAL,
    CONF_PHONE_NAME,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_UID,
    CONF_USER_AGENT,
    CONF_WIFI_SN,
    DEFAULT_IMAGE_ROTATION,
    DEFAULT_INFO_INTERVAL,
    DEFAULT_PHONE_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USER_AGENT,
    DOMAIN,
    IMAGE_ROTATIONS,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _device_title(device: dict[str, Any]) -> str:
    product = device.get("product") or {}
    name = device.get("lockNickname") or "凯迪仕门锁"
    model = product.get("abbreviation") or device.get("productModel")
    return f"{name}（{model}）" if model else name


class KaadasConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._input: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []

    async def _async_fetch_devices(
        self, user_input: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None]:
        api = KaadasApi(
            async_get_clientsession(self.hass),
            token=user_input[CONF_TOKEN].strip(),
            uid=user_input[CONF_UID].strip(),
            user_agent=user_input.get(CONF_USER_AGENT, DEFAULT_USER_AGENT),
            phone_name=user_input.get(CONF_PHONE_NAME, DEFAULT_PHONE_NAME),
        )
        try:
            devices = await api.async_get_devices()
        except KaadasAuthError:
            return [], "invalid_auth"
        except KaadasError:
            _LOGGER.exception("连接凯迪仕云端失败")
            return [], "cannot_connect"
        if not devices:
            return [], "no_devices"
        return devices, None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            devices, error = await self._async_fetch_devices(user_input)
            if error:
                errors["base"] = error
            else:
                self._input = {
                    **user_input,
                    CONF_TOKEN: user_input[CONF_TOKEN].strip(),
                    CONF_UID: user_input[CONF_UID].strip(),
                }
                self._devices = devices
                if len(devices) == 1:
                    return await self._async_create(devices[0])
                return await self.async_step_device()

        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN): str,
                vol.Required(CONF_UID): str,
                vol.Optional(CONF_USER_AGENT, default=DEFAULT_USER_AGENT): str,
                vol.Optional(CONF_PHONE_NAME, default=DEFAULT_PHONE_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            device = next(d for d in self._devices if d.get("wifiSN") == user_input[CONF_WIFI_SN])
            return await self._async_create(device)

        options = [
            SelectOptionDict(value=d["wifiSN"], label=_device_title(d))
            for d in self._devices
            if d.get("wifiSN")
        ]
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {vol.Required(CONF_WIFI_SN): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    async def _async_create(self, device: dict[str, Any]) -> ConfigFlowResult:
        wifi_sn = device["wifiSN"]
        await self.async_set_unique_id(wifi_sn)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=_device_title(device),
            data={**self._input, CONF_WIFI_SN: wifi_sn},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            new_data = {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN].strip()}
            devices, error = await self._async_fetch_devices(new_data)
            if error:
                errors["base"] = error
            elif not any(d.get("wifiSN") == entry.data[CONF_WIFI_SN] for d in devices):
                errors["base"] = "device_not_found"
            else:
                return self.async_update_reload_and_abort(entry, data=new_data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> KaadasOptionsFlow:
        return KaadasOptionsFlow()


class KaadasOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(int, vol.Range(min=MIN_SCAN_INTERVAL, max=600)),
                    vol.Required(
                        CONF_INFO_INTERVAL,
                        default=options.get(CONF_INFO_INTERVAL, DEFAULT_INFO_INTERVAL),
                    ): vol.All(int, vol.Range(min=60, max=86400)),
                    vol.Required(
                        CONF_IMAGE_ROTATION,
                        default=str(options.get(CONF_IMAGE_ROTATION, DEFAULT_IMAGE_ROTATION)),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[str(r) for r in IMAGE_ROTATIONS],
                            translation_key="image_rotation",
                        )
                    ),
                }
            ),
        )
