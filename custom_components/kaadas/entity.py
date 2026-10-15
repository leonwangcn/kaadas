"""实体基类。"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KaadasCoordinator


class KaadasEntity(CoordinatorEntity[KaadasCoordinator]):
    """所有实体挂在同一个门锁设备下。"""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KaadasCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.wifi_sn}_{key}"
        self._attr_translation_key = key
        device = coordinator.data.device
        product = device.get("product") or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.wifi_sn)},
            name=device.get("lockNickname") or "凯迪仕门锁",
            manufacturer="Kaadas 凯迪仕",
            model=product.get("abbreviation") or device.get("productModel"),
            model_id=device.get("productModel"),
            serial_number=coordinator.wifi_sn,
            sw_version=device.get("wifiVersion"),
        )
