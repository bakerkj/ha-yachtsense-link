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
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_HOME,
    DATA_IO,
    DATA_LAN,
    DATA_MOBILE,
    DATA_SELFCHECK,
    DATA_UPGRADE,
    DEV_CELLULAR,
    DEV_HUB,
    DEV_IO,
    DEV_NETWORK,
    DEV_WIFI_AP,
    DEV_WIFI_UPLINK,
    DOMAIN,
)
from .entity import YsEntity

# GetUpgradeStatusAndProgress reports 3 while no upgrade is running.
_UPGRADE_IDLE = 3


def _sect(d: dict[str, Any], name: str) -> dict[str, Any]:
    return (d.get(DATA_HOME) or {}).get(name) or {}


def _cellular_up(d: dict[str, Any]) -> bool | None:
    mob = _sect(d, "mobile")
    return mob.get("ipv4netstatus") == 1 if mob else None


def _sim(d: dict[str, Any]) -> dict[str, Any]:
    m = d.get(DATA_MOBILE) or {}
    sims = m.get("sim") or []
    idx = m.get("active_sim") or 0
    if isinstance(idx, int) and 0 <= idx < len(sims):
        return sims[idx]
    return sims[0] if sims else {}


def _flag(section: dict[str, Any], key: str) -> bool | None:
    """A router 0/1 flag, or None when the section wasn't returned."""
    val = section.get(key)
    return val == 1 if isinstance(val, int) and not isinstance(val, bool) else None


def _self_check_problem(d: dict[str, Any]) -> bool | None:
    sc = (d.get(DATA_SELFCHECK) or {}).get("SelfCheck")
    # Non-zero means at least one internal module failed its self-check.
    return sc != 0 if isinstance(sc, int) and not isinstance(sc, bool) else None


def _upgrading(d: dict[str, Any]) -> bool | None:
    status = (d.get(DATA_UPGRADE) or {}).get("status")
    return (
        status != _UPGRADE_IDLE
        if isinstance(status, int) and not isinstance(status, bool)
        else None
    )


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
    YsBinaryDescription(
        key="hub_self_check",
        name="Self-check",
        group=DEV_HUB,
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=_self_check_problem,
    ),
    YsBinaryDescription(
        key="hub_upgrading",
        name="Upgrade in progress",
        group=DEV_HUB,
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_upgrading,
    ),
    YsBinaryDescription(
        key="cellular_ipv6",
        name="IPv6",
        group=DEV_CELLULAR,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: _flag(_sect(d, "mobile"), "ipv6netstatus"),
    ),
    YsBinaryDescription(
        key="cellular_data_enabled",
        name="Mobile data enabled",
        group=DEV_CELLULAR,
        icon="mdi:network",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: _flag(_sim(d), "mobile_data"),
    ),
    YsBinaryDescription(
        key="cellular_roaming_enabled",
        name="Roaming allowed",
        group=DEV_CELLULAR,
        icon="mdi:earth",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: _flag(_sim(d), "roam_data"),
    ),
    YsBinaryDescription(
        key="net_lan_ipv6",
        name="LAN IPv6",
        group=DEV_NETWORK,
        icon="mdi:ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: _flag(d.get(DATA_LAN) or {}, "Eth_IPv6_Enable"),
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
