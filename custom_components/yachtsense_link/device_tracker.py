# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Device tracker platform for the YachtSense Link integration (GPS position)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_GPS, DEV_GPS, DOMAIN
from .entity import YsEntity


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _position(d: dict[str, Any]) -> tuple[float | None, float | None]:
    g = d.get(DATA_GPS) or {}
    lat, lng = _num(g.get("lat")), _num(g.get("lng"))
    # (0, 0) is the router's "no fix" value, not a real position.
    if lat is None or lng is None or (lat == 0.0 and lng == 0.0):
        return None, None
    return lat, lng


class YsDeviceTracker(YsEntity, TrackerEntity):
    """The vessel's GPS position as reported by the router."""

    _attr_name = "Position"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, coordinator: Any) -> None:
        super().__init__(coordinator, DEV_GPS, "gps_position")

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return _position(self.coordinator.data)[0]

    @property
    def longitude(self) -> float | None:
        return _position(self.coordinator.data)[1]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the YachtSense Link device tracker."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([YsDeviceTracker(coordinator)])
