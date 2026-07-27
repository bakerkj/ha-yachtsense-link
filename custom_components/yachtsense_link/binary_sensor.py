# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Binary sensor platform for the YachtSense Link integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_HOME,
    DATA_IO,
    DEV_CELLULAR,
    DEV_IO,
    DEV_NETWORK,
    DEV_WIFI_AP,
    DEV_WIFI_UPLINK,
    DOMAIN,
)
from .entity import YsEntity


def _sect(d: dict[str, Any], name: str) -> dict[str, Any]:
    return (d.get(DATA_HOME) or {}).get(name) or {}


def _cellular_up(d: dict[str, Any]) -> bool | None:
    mob = _sect(d, "mobile")
    return mob.get("ipv4netstatus") == 1 if mob else None


def _io_switch_fn(idx: int) -> Callable[[dict[str, Any]], bool | None]:
    def fn(d: dict[str, Any]) -> bool | None:
        chans = (
            (d.get(DATA_IO) or {}).get("io_date")
            or (d.get(DATA_IO) or {}).get("io_data")
            or []
        )
        if idx >= len(chans) or not isinstance(chans[idx], dict):
            return None
        ch = chans[idx]
        return ch.get("status") == 1 and ch.get("types") not in (0, None)

    return fn


@dataclass(frozen=True, kw_only=True)
class YsBinaryDescription(BinarySensorEntityDescription):
    group: str
    is_on_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[YsBinaryDescription, ...] = (
    YsBinaryDescription(
        key="cellular_status",
        name="Status",
        group=DEV_CELLULAR,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=_cellular_up,
    ),
    YsBinaryDescription(
        key="net_cloud",
        name="Cloud connection",
        group=DEV_NETWORK,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=lambda d: (
            (_sect(d, "cloud").get("cloud_status") == 1) if _sect(d, "cloud") else None
        ),
    ),
    YsBinaryDescription(
        key="net_wifi_ap",
        name="Status",
        group=DEV_WIFI_AP,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=lambda d: (
            (_sect(d, "ap").get("status") == 1) if _sect(d, "ap") else None
        ),
    ),
    YsBinaryDescription(
        key="net_wifi_uplink",
        name="Status",
        group=DEV_WIFI_UPLINK,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=lambda d: (
            (_sect(d, "sta").get("status") == 1) if _sect(d, "sta") else None
        ),
    ),
)

# I/O channels 5-8 are switch channels.
IO_SWITCH_SENSORS: tuple[YsBinaryDescription, ...] = tuple(
    YsBinaryDescription(
        key=f"io_ch{n}",
        name=f"Channel {n}",
        group=DEV_IO,
        icon="mdi:toggle-switch-variant",
        is_on_fn=_io_switch_fn(n - 1),
    )
    for n in range(5, 9)
)


class YsBinarySensor(YsEntity, BinarySensorEntity):
    """A YachtSense Link binary sensor."""

    entity_description: YsBinaryDescription

    def __init__(self, coordinator: Any, description: YsBinaryDescription) -> None:
        super().__init__(coordinator, description.group, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up YachtSense Link binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        YsBinarySensor(coordinator, desc)
        for desc in (*BINARY_SENSORS, *IO_SWITCH_SENSORS)
    )
