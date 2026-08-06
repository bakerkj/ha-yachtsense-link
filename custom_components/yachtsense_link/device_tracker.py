# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Device tracker platform for the YachtSense Link integration (GPS position)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_GNSS, DEV_GPS, DOMAIN, GNSS_MAX_FIX_AGE
from .entity import YsEntity


def _num(v: Any) -> float | None:
    if isinstance(v, str):  # the GNSS report sends numbers as strings
        try:
            return float(v)
        except ValueError:
            return None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _position(d: dict[str, Any]) -> tuple[float | None, float | None]:
    """The vessel's position from the GNSS report, or (None, None).

    There is deliberately no second source: anything without a timestamp cannot
    be checked for having stopped updating, so reporting nothing is the safer
    failure.
    """
    report = d.get(DATA_GNSS)
    if not report:
        return None, None
    # Fix 0 means the receiver has no solution; a report whose timestamp has
    # stopped advancing is a frozen cache, which looks identical to a live fix
    # in the payload itself. Both must read as "no position", not as a position.
    g = report.get("gnss") or {}
    if str(g.get("Fix", "0")) == "0":
        return None, None
    age = report.get("fix_age")
    if isinstance(age, (int, float)) and age > GNSS_MAX_FIX_AGE:
        return None, None
    lat, lng = _num(g.get("Latitude")), _num(g.get("Longitude"))
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
