# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Device tracker platform for the YachtSense Link integration (GPS position)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_GNSS, DEV_GNSS, DOMAIN, GNSS_MAX_FIX_AGE, GNSS_NO_FIX
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

    There is deliberately no second source: a position that cannot be checked
    for having stopped updating is worse than none at all, so reporting nothing
    is the safer failure.
    """
    report = d.get(DATA_GNSS)
    if not report:
        return None, None
    g = report.get("gnss") or {}
    if str(g.get("Fix", "0")) in GNSS_NO_FIX:
        return None, None
    # Two ways a report can be old, neither of which the payload distinguishes
    # from a live fix on its own: the receiver stalled, or nothing was read for
    # a while. Both are measured entirely in our own clock, so they cannot
    # drift.
    #
    # observation_lag is deliberately NOT among them. It is the difference
    # between our clock and the receiver's counter, and that counter does not
    # advance at wall-clock rate, so the difference grows without bound and
    # would eventually retire every position regardless of its age. It is
    # published as an attribute only.
    for key in ("fix_age", "report_age"):
        age = report.get(key)
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
        super().__init__(coordinator, DEV_GNSS, "gnss_position")
        self._pos: tuple[float | None, float | None] = _position(coordinator.data or {})

    def _handle_coordinator_update(self) -> None:
        # Resolved once per update rather than once per coordinate, so latitude
        # and longitude cannot disagree if a report expires between the two
        # property reads.
        self._pos = _position(self.coordinator.data or {})
        super()._handle_coordinator_update()

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self._pos[0]

    @property
    def longitude(self) -> float | None:
        return self._pos[1]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Surface why a position is missing, which is otherwise invisible.

        Each of these is a way the report can be too old to publish; without
        them a blanked tracker gives no clue which one fired.
        """
        report = (self.coordinator.data or {}).get(DATA_GNSS) or {}
        attrs: dict[str, Any] = {
            key: round(value, 1)
            for key in ("fix_age", "report_age", "observation_lag")
            if isinstance(value := report.get(key), (int, float))
        }
        fix = (report.get("gnss") or {}).get("Fix")
        if fix is not None:
            attrs["fix"] = str(fix)
        return attrs


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the YachtSense Link device tracker."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([YsDeviceTracker(coordinator)])
