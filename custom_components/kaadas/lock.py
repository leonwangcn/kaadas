"""只读门锁：状态来自最近一条开/关锁记录，不支持远程开关锁。"""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, OP_TYPE_LOCK, OP_TYPE_UNLOCK
from .coordinator import KaadasConfigEntry, KaadasCoordinator
from .entity import KaadasEntity
from .event import event_attributes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KaadasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([KaadasLock(entry.runtime_data)])


class KaadasLock(KaadasEntity, LockEntity):
    """让 HomeKit 能显示门锁状态。开关锁请求一律拒绝。"""

    def __init__(self, coordinator: KaadasCoordinator) -> None:
        super().__init__(coordinator, "lock")

    @property
    def is_locked(self) -> bool | None:
        record = self.coordinator.data.last_operation
        if record is None:
            return None
        if record.get("type") == OP_TYPE_LOCK:
            return True
        if record.get("type") == OP_TYPE_UNLOCK:
            return False
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        record = self.coordinator.data.last_operation
        return event_attributes(record) if record else None

    async def async_lock(self, **kwargs: Any) -> None:
        self._reject("is_locking")

    async def async_unlock(self, **kwargs: Any) -> None:
        self._reject("is_unlocking")

    async def async_open(self, **kwargs: Any) -> None:
        self._reject("is_opening")

    def _reject(self, transition: str) -> None:
        # HomeKit 发出指令后会把目标状态设成新值，只有实体状态变化才会被重置回去，
        # 否则家庭 App 会一直显示"正在开锁"。这里先报一次过渡状态，再恢复原状态。
        setattr(self, f"_attr_{transition}", True)
        self.async_write_ha_state()
        setattr(self, f"_attr_{transition}", False)
        self.async_write_ha_state()
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="read_only_lock")
