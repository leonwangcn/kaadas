"""诊断信息：脱敏后的设备信息和最近记录，方便排查字段差异。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, CONF_UID, CONF_WIFI_SN
from .coordinator import KaadasConfigEntry

TO_REDACT = {
    CONF_TOKEN,
    CONF_UID,
    CONF_WIFI_SN,
    "uid",
    "adminUid",
    "wifiSN",
    "esn",
    "productSN",
    "lockSn",
    "device_sn",
    "device_did",
    "mac",
    "lockMac",
    "p2p_password",
    "randomCode",
    "adminPwd",
    "uname",
    "adminName",
    "account",
    "userNickname",
    "pwdNickname",
    "thumbUrl",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: KaadasConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": async_redact_data(asdict(data), TO_REDACT),
        "snapshot_cached": coordinator.snapshot_image is not None,
        "push_enabled": coordinator.push is not None,
        "push_connected": bool(coordinator.push and coordinator.push.connected),
        "update_interval": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
    }
