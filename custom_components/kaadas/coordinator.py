"""轮询凯迪仕云端，整理出设备状态、最新记录和新事件。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KaadasApi, KaadasAuthError, KaadasError
from .const import (
    ALARM_TYPE_BOLT_JAMMED,
    ALARM_TYPE_LOITERING,
    DOMAIN,
    EVENT_MAX_AGE,
    OP_TYPE_LOCK,
    OP_TYPE_UNLOCK,
    SEEN_IDS_LIMIT,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

# 事件种类
KIND_DOORBELL = "doorbell"
KIND_LOITERING = "loitering"
KIND_UNLOCKED = "unlocked"
KIND_LOCKED = "locked"
KIND_BOLT_JAMMED = "bolt_jammed"
KIND_ALARM = "alarm"

type KaadasConfigEntry = ConfigEntry[KaadasCoordinator]


@dataclass(frozen=True)
class KaadasEvent:
    """一条新出现的记录。"""

    kind: str
    record: dict[str, Any]


@dataclass
class KaadasData:
    """一次轮询的结果。"""

    seq: int
    device: dict[str, Any]
    last_operation: dict[str, Any] | None = None
    last_unlock: dict[str, Any] | None = None
    last_doorbell: dict[str, Any] | None = None
    last_loitering: dict[str, Any] | None = None
    last_snapshot: dict[str, Any] | None = None
    new_events: list[KaadasEvent] = field(default_factory=list)


def record_id(record: dict[str, Any]) -> str:
    """记录的唯一标识。latest-five 之类的接口没有 id，用时间+类型兜底。"""
    rid = record.get("_id") or record.get("id")
    if rid:
        return str(rid)
    return f"{record.get('time')}-{record.get('type')}-{record.get('eventId', '')}"


def record_time(record: dict[str, Any]) -> int:
    """记录发生时间（Unix 秒）。startTime 比实际多 8 小时，不能用。"""
    try:
        return int(record.get("time") or 0)
    except (TypeError, ValueError):
        return 0


def _classify_operation(record: dict[str, Any]) -> str | None:
    rtype = record.get("type")
    if rtype == OP_TYPE_UNLOCK:
        return KIND_UNLOCKED
    if rtype == OP_TYPE_LOCK:
        return KIND_LOCKED
    return None


def _classify_visit(record: dict[str, Any]) -> str | None:
    # 目前只见过 96。其他 type 先也当门铃，原始值会带在事件属性里
    return KIND_DOORBELL


def _classify_alarm(record: dict[str, Any]) -> str | None:
    rtype = record.get("type")
    if rtype == ALARM_TYPE_LOITERING:
        return KIND_LOITERING
    if rtype == ALARM_TYPE_BOLT_JAMMED:
        return KIND_BOLT_JAMMED
    return KIND_ALARM


_CLASSIFIERS = {
    "operation": _classify_operation,
    "visit": _classify_visit,
    "alarm": _classify_alarm,
}


def _rotated_url(url: str, rotation: int) -> str:
    """抓拍图存在阿里云 OSS 上，让 OSS 在服务端旋转，HA 这边不用处理图片。"""
    if not rotation or "aliyuncs.com" not in url or "?" in url:
        return url
    return f"{url}?x-oss-process=image/rotate,{rotation}"


def _latest(records: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    matched = [r for r in records if predicate(r)]
    return max(matched, key=record_time) if matched else None


class KaadasCoordinator(DataUpdateCoordinator[KaadasData]):
    """一把门锁一个 coordinator。"""

    config_entry: KaadasConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: KaadasConfigEntry,
        api: KaadasApi,
        wifi_sn: str,
        scan_interval: int,
        info_interval: int,
        image_rotation: int = 0,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{wifi_sn}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self.wifi_sn = wifi_sn
        self._info_interval = info_interval
        self._image_rotation = image_rotation
        self._device: dict[str, Any] | None = None
        self._device_fetched_at = 0.0
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        # 每类记录已处理过的 id。某类不在字典里，说明是第一次见到，只记下不触发
        self._seen: dict[str, list[str]] = {}
        self._seq = 0
        self.snapshot_image: bytes | None = None
        self.snapshot_event_id: str | None = None

    async def async_load(self) -> None:
        """读取上次运行记下的已处理 id，避免重启后重复推送。"""
        stored = await self._store.async_load()
        if stored and isinstance(stored.get("seen"), dict):
            self._seen = {k: list(v) for k, v in stored["seen"].items()}

    async def _async_update_data(self) -> KaadasData:
        try:
            device = await self._async_get_device()
            operations, visits, alarms = await asyncio.gather(
                self.api.async_get_operations(self.wifi_sn),
                self.api.async_get_visits(self.wifi_sn),
                self.api.async_get_alarms(self.wifi_sn),
            )
        except KaadasAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except KaadasError as err:
            raise UpdateFailed(str(err)) from err

        new_events = self._collect_new_events(
            {"operation": operations, "visit": visits, "alarm": alarms}
        )

        snapshots = [r for r in visits + alarms if r.get("thumbUrl")]
        last_snapshot = max(snapshots, key=record_time) if snapshots else None
        if last_snapshot:
            await self._async_update_snapshot(last_snapshot)

        self._seq += 1
        return KaadasData(
            seq=self._seq,
            device=device,
            last_operation=max(operations, key=record_time) if operations else None,
            last_unlock=_latest(operations, lambda r: r.get("type") == OP_TYPE_UNLOCK),
            last_doorbell=_latest(visits, lambda _: True),
            last_loitering=_latest(alarms, lambda r: r.get("type") == ALARM_TYPE_LOITERING),
            last_snapshot=last_snapshot,
            new_events=new_events,
        )

    async def _async_get_device(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._device is not None and now - self._device_fetched_at < self._info_interval:
            return self._device
        devices = await self.api.async_get_devices()
        device = next((d for d in devices if d.get("wifiSN") == self.wifi_sn), None)
        if device is None:
            raise UpdateFailed(f"账号下找不到门锁 {self.wifi_sn}")
        self._device = device
        self._device_fetched_at = now
        return device

    def _collect_new_events(
        self, records_by_category: dict[str, list[dict[str, Any]]]
    ) -> list[KaadasEvent]:
        now = time.time()
        events: list[KaadasEvent] = []
        changed = False
        for category, records in records_by_category.items():
            first_time = category not in self._seen
            seen = self._seen.setdefault(category, [])
            seen_set = set(seen)
            # 接口按时间倒序返回，按时间正序处理，事件触发顺序才和实际一致
            for record in sorted(records, key=record_time):
                rid = record_id(record)
                if rid in seen_set:
                    continue
                seen.append(rid)
                seen_set.add(rid)
                changed = True
                if first_time or now - record_time(record) > EVENT_MAX_AGE:
                    continue
                kind = _CLASSIFIERS[category](record)
                if kind is None:
                    _LOGGER.debug("忽略未知 %s 记录：type=%s", category, record.get("type"))
                    continue
                events.append(KaadasEvent(kind, record))
            del seen[:-SEEN_IDS_LIMIT]
        if changed:
            self._store.async_delay_save(lambda: {"seen": self._seen}, 5)
        events.sort(key=lambda e: record_time(e.record))
        return events

    async def _async_update_snapshot(self, record: dict[str, Any]) -> None:
        event_id = str(record.get("eventId") or record_id(record))
        if event_id == self.snapshot_event_id and self.snapshot_image is not None:
            return
        image = await self.api.async_get_image(
            _rotated_url(record["thumbUrl"], self._image_rotation)
        )
        if image is None:
            # 图片可能还在上传，下一轮再试；先保留上一张
            return
        self.snapshot_image = image
        self.snapshot_event_id = event_id
