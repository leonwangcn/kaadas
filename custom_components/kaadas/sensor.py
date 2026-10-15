"""传感器：电量、最近动态、最近开锁人、最近门铃/徘徊时间、固件信息。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import KaadasConfigEntry, KaadasCoordinator, KaadasData
from .entity import KaadasEntity
from .event import event_attributes


def _timestamp(record: dict[str, Any] | None) -> datetime | None:
    if not record or not record.get("time"):
        return None
    return dt_util.utc_from_timestamp(int(record["time"]))


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, kw_only=True)
class KaadasSensorDescription(SensorEntityDescription):
    value_fn: Callable[[KaadasData], Any]
    attrs_fn: Callable[[KaadasData], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[KaadasSensorDescription, ...] = (
    KaadasSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _int(d.device.get("power")),
    ),
    KaadasSensorDescription(
        key="last_activity",
        value_fn=lambda d: (d.last_operation or {}).get("textContent"),
        attrs_fn=lambda d: event_attributes(d.last_operation) if d.last_operation else {},
    ),
    KaadasSensorDescription(
        key="last_unlocked_by",
        value_fn=lambda d: (
            (d.last_unlock or {}).get("userNickname") or (d.last_unlock or {}).get("pwdNickname")
        ),
        attrs_fn=lambda d: event_attributes(d.last_unlock) if d.last_unlock else {},
    ),
    KaadasSensorDescription(
        key="last_unlock_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _timestamp(d.last_unlock),
    ),
    KaadasSensorDescription(
        key="last_doorbell",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _timestamp(d.last_doorbell),
    ),
    KaadasSensorDescription(
        key="last_loitering",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _timestamp(d.last_loitering),
    ),
    KaadasSensorDescription(
        key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device.get("wifiName"),
    ),
    KaadasSensorDescription(
        key="camera_firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device.get("camera_version"),
        attrs_fn=lambda d: {
            "wifi": d.device.get("wifiVersion"),
            "mcu": d.device.get("mcu_version"),
            "front_panel": d.device.get("frontPanelVersion"),
            "back_panel": d.device.get("backPanelVersion"),
            "face": d.device.get("faceVersion"),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KaadasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(KaadasSensor(coordinator, d) for d in SENSOR_DESCRIPTIONS)


class KaadasSensor(KaadasEntity, SensorEntity):
    entity_description: KaadasSensorDescription

    def __init__(
        self, coordinator: KaadasCoordinator, description: KaadasSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
