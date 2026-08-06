# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Base entity and device grouping for the YachtSense Link integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEV_CELLULAR,
    DEV_GNSS,
    DEV_HUB,
    DEV_IO,
    DEV_NETWORK,
    DEV_WIFI_AP,
    DEV_WIFI_UPLINK,
    DOMAIN,
)
from .coordinator import YachtSenseLinkCoordinator

GROUP_LABELS: dict[str, str] = {
    DEV_HUB: "YachtSense Link",
    DEV_CELLULAR: "Cellular",
    DEV_NETWORK: "Network",
    DEV_WIFI_AP: "WiFi Access Point",
    DEV_WIFI_UPLINK: "WiFi Uplink",
    DEV_GNSS: "GNSS",
    DEV_IO: "I/O",
}


class YsEntity(CoordinatorEntity[YachtSenseLinkCoordinator]):
    """Base entity: unique_id and per-group DeviceInfo (all via the hub)."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: YachtSenseLinkCoordinator, group_id: str, key: str
    ) -> None:
        super().__init__(coordinator)
        base = coordinator.base_id
        self._attr_unique_id = f"{base}_{key}"

        hub_ident = (DOMAIN, f"{base}_{DEV_HUB}")
        info = DeviceInfo(
            identifiers={(DOMAIN, f"{base}_{group_id}")},
            name=GROUP_LABELS.get(group_id, group_id),
            manufacturer="Raymarine",
            model="YachtSense Link",
        )
        if group_id != DEV_HUB:
            info["via_device"] = hub_ident
        self._attr_device_info = info
