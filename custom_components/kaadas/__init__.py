"""凯迪仕门锁集成（只读，云端轮询）。"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KaadasApi
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
    PLATFORMS,
)
from .coordinator import KaadasConfigEntry, KaadasCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: KaadasConfigEntry) -> bool:
    data = entry.data
    api = KaadasApi(
        async_get_clientsession(hass),
        token=data[CONF_TOKEN],
        uid=data[CONF_UID],
        user_agent=data.get(CONF_USER_AGENT, DEFAULT_USER_AGENT),
        phone_name=data.get(CONF_PHONE_NAME, DEFAULT_PHONE_NAME),
    )
    coordinator = KaadasCoordinator(
        hass,
        entry,
        api,
        wifi_sn=data[CONF_WIFI_SN],
        scan_interval=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        info_interval=entry.options.get(CONF_INFO_INTERVAL, DEFAULT_INFO_INTERVAL),
        image_rotation=int(entry.options.get(CONF_IMAGE_ROTATION, DEFAULT_IMAGE_ROTATION)),
    )
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KaadasConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
