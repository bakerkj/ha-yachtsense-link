# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Data update coordinator for the YachtSense Link integration.

One poll at the configured interval gathers every method and exposes a merged
data dict; all entities update together on that interval. Throughput is the
per-cycle delta of the cumulative data counter. HA's own statistics build
hourly/daily/monthly usage from that cumulative counter (a ``total_increasing``
sensor), so no bespoke bucketing is needed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import YachtSenseLinkApi, YsAuthError, YsError
from .const import (
    DATA_CONNECTED,
    DATA_GPS,
    DATA_HOME,
    DATA_HUB,
    DATA_IO,
    DATA_MOBILE,
    DATA_THROUGHPUT,
    DOMAIN,
    IO_READ_PARAMS,
    METHOD_CONNECTED,
    METHOD_GPS,
    METHOD_HOME,
    METHOD_HUB,
    METHOD_IO,
    METHOD_MOBILE,
)

_LOGGER = logging.getLogger(__name__)

# (merged-data key, RPC method, params)
_CALLS: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    (DATA_HOME, METHOD_HOME, None),
    (DATA_MOBILE, METHOD_MOBILE, None),
    (DATA_HUB, METHOD_HUB, None),
    (DATA_CONNECTED, METHOD_CONNECTED, None),
    (DATA_GPS, METHOD_GPS, None),
    (DATA_IO, METHOD_IO, IO_READ_PARAMS),
)


def _active_sim(mobile: dict[str, Any] | None) -> dict[str, Any]:
    sims = (mobile or {}).get("sim") or []
    idx = (mobile or {}).get("active_sim") or 0
    if isinstance(idx, int) and 0 <= idx < len(sims):
        return sims[idx]
    return sims[0] if sims else {}


class YachtSenseLinkCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the router's JSON-RPC API and exposes a merged data dict."""

    def __init__(
        self, hass: HomeAssistant, api: YachtSenseLinkApi, update_interval: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.api = api
        self.base_id: str = ""  # set by __init__.py from the config entry
        self._prev_used: float | None = None
        self._prev_used_ts: float | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        # Log in once up front so the concurrent calls below share the session.
        try:
            await self.api.login()
        except YsAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except YsError as exc:
            raise UpdateFailed(str(exc)) from exc

        results = await asyncio.gather(
            *(self.api.call(method, params) for _key, method, params in _CALLS),
            return_exceptions=True,
        )

        data: dict[str, Any] = {}
        auth_failures = 0
        failures = 0
        for (key, method, _params), res in zip(_CALLS, results):
            if isinstance(res, YsAuthError):
                auth_failures += 1
                failures += 1
                data[key] = None
            elif isinstance(res, Exception):
                _LOGGER.debug("%s failed: %s", method, res)
                failures += 1
                data[key] = None
            else:
                data[key] = res

        if auth_failures == len(_CALLS):
            raise ConfigEntryAuthFailed("router rejected the session on every call")
        # A cycle where every call failed (but not all on auth) is a full data
        # loss -- fail the update so entities go unavailable rather than showing
        # a stale/blank state as if the poll had succeeded.
        if failures == len(_CALLS):
            raise UpdateFailed("router returned no data on any call")

        data[DATA_THROUGHPUT] = self._throughput(data.get(DATA_MOBILE))
        return data

    def _throughput(self, mobile: dict[str, Any] | None) -> dict[str, float] | None:
        used = _active_sim(mobile).get("current_data_used")
        if not isinstance(used, (int, float)):
            return None
        used = float(used)
        now = dt_util.utcnow().timestamp()
        rate = 0.0
        if self._prev_used is not None and self._prev_used_ts is not None:
            dt = now - self._prev_used_ts
            delta = used - self._prev_used
            if delta < 0:  # billing-cycle reset
                delta = 0.0
            if dt > 0:
                rate = delta / (dt / 3600.0)  # MB per hour
        self._prev_used = used
        self._prev_used_ts = now
        return {"rate_mb_per_h": round(rate, 2)}
