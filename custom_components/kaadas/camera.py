"""门口抓拍摄像头：显示最近一次门铃或徘徊的抓拍图。没有视频流。"""

from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaadasConfigEntry, KaadasCoordinator
from .entity import KaadasEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KaadasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([KaadasSnapshotCamera(entry.runtime_data)])


class KaadasSnapshotCamera(KaadasEntity, Camera):
    """抓拍图由 coordinator 在发现新记录时下载并缓存在内存里，不写磁盘。"""

    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator: KaadasCoordinator) -> None:
        KaadasEntity.__init__(self, coordinator, "snapshot")
        Camera.__init__(self)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        record = self.coordinator.data.last_snapshot or {}
        return {
            "event": record.get("textContent"),
            "event_time": record.get("time"),
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self.coordinator.snapshot_image
