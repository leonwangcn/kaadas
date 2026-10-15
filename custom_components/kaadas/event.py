"""事件实体：门铃、徘徊、开关锁、报警。供 HomeKit 门铃/移动通知和自动化使用。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.event import (
    EventDeviceClass,
    EventEntity,
    EventEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import PWD_TYPE_METHODS
from .coordinator import (
    KIND_ALARM,
    KIND_BOLT_JAMMED,
    KIND_DOORBELL,
    KIND_LOCKED,
    KIND_LOITERING,
    KIND_UNLOCKED,
    KaadasConfigEntry,
    KaadasCoordinator,
    KaadasEvent,
)
from .entity import KaadasEntity


@dataclass(frozen=True, kw_only=True)
class KaadasEventDescription(EventEntityDescription):
    """kinds：coordinator 事件种类 -> HA event_type。"""

    kinds: dict[str, str]


EVENT_DESCRIPTIONS: tuple[KaadasEventDescription, ...] = (
    KaadasEventDescription(
        key="doorbell",
        device_class=EventDeviceClass.DOORBELL,
        event_types=["ring"],
        kinds={KIND_DOORBELL: "ring"},
    ),
    KaadasEventDescription(
        key="loitering",
        device_class=EventDeviceClass.MOTION,
        event_types=["loitering"],
        kinds={KIND_LOITERING: "loitering"},
    ),
    KaadasEventDescription(
        key="lock_activity",
        event_types=["unlocked", "locked"],
        kinds={KIND_UNLOCKED: "unlocked", KIND_LOCKED: "locked"},
    ),
    KaadasEventDescription(
        key="alarm",
        event_types=["bolt_jammed", "alarm"],
        kinds={KIND_BOLT_JAMMED: "bolt_jammed", KIND_ALARM: "alarm"},
    ),
)


def unlock_method(record: dict[str, Any]) -> str:
    """开锁方式。没见过的 pwdType 返回 other，原始值另放在 pwd_type 属性里。"""
    pwd_type = record.get("pwdType")
    return PWD_TYPE_METHODS.get(pwd_type, "other") if pwd_type is not None else "other"


def event_attributes(record: dict[str, Any]) -> dict[str, Any]:
    """事件属性。不放图片链接：凯迪仕的抓拍图链接无需鉴权，写进事件历史等于公开。"""
    attrs: dict[str, Any] = {
        "text": record.get("textContent"),
        "time": record.get("time"),
        "record_type": record.get("type"),
    }
    if record.get("eventId"):
        attrs["has_snapshot"] = bool(record.get("thumbUrl"))
    if record.get("pwdType") is not None:
        attrs["method"] = unlock_method(record)
        attrs["pwd_type"] = record.get("pwdType")
        attrs["user_number"] = record.get("pwdNum")
        attrs["user_name"] = record.get("userNickname") or record.get("pwdNickname")
    return attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KaadasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(KaadasEventEntity(coordinator, d) for d in EVENT_DESCRIPTIONS)


class KaadasEventEntity(KaadasEntity, EventEntity):
    entity_description: KaadasEventDescription

    def __init__(self, coordinator: KaadasCoordinator, description: KaadasEventDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        # 轮询失败时 coordinator 也会通知实体，用 seq 保证同一批事件只触发一次
        self._handled_seq: int | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # 启动时的第一轮轮询发生在实体创建之前，重启期间来的新记录在这里补触发
        self._fire_new_events()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._fire_new_events()
        super()._handle_coordinator_update()

    @callback
    def _fire_new_events(self) -> None:
        data = self.coordinator.data
        if data.seq == self._handled_seq:
            return
        self._handled_seq = data.seq
        for event in data.new_events:
            self._fire(event)

    def _fire(self, event: KaadasEvent) -> None:
        event_type = self.entity_description.kinds.get(event.kind)
        if event_type is None:
            return
        self._trigger_event(event_type, event_attributes(event.record))
        self.async_write_ha_state()
