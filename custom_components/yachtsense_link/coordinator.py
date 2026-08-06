# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Data update coordinator for the YachtSense Link integration.

One poll at the configured interval gathers every live method and exposes a
merged data dict; all entities update together on that interval. Throughput is
the per-cycle delta of the cumulative data counter. HA's own statistics build
hourly/daily/monthly usage from that cumulative counter (a ``total_increasing``
sensor), so no bespoke bucketing is needed.

Router configuration (WiFi, APN, LAN) changes only when someone edits it, so
those methods are refreshed every ``SLOW_EVERY`` cycles and their last-known
values carried forward in between -- an embedded router should not field eleven
concurrent RPCs a minute just to re-read static settings.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import YachtSenseLinkApi, YsAuthError, YsError, YsUnreachableError
from .const import (
    DATA_APN,
    DATA_CONNECTED,
    DATA_GNSS,
    DATA_HOME,
    DATA_HUB,
    DATA_IO,
    DATA_LAN,
    DATA_MOBILE,
    DATA_SELFCHECK,
    DATA_THROUGHPUT,
    DATA_UPGRADE,
    DATA_WLAN,
    DOMAIN,
    IO_READ_PARAMS,
    LAN_READ_PARAMS,
    METHOD_APN,
    METHOD_CONNECTED,
    METHOD_HOME,
    METHOD_HUB,
    METHOD_IO,
    METHOD_LAN,
    METHOD_MOBILE,
    METHOD_SELFCHECK,
    METHOD_UPGRADE,
    METHOD_WLAN,
    SLOW_EVERY,
)

_LOGGER = logging.getLogger(__name__)

# (merged-data key, RPC method, params), polled every cycle.
_CALLS: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    (DATA_HOME, METHOD_HOME, None),
    (DATA_MOBILE, METHOD_MOBILE, None),
    (DATA_HUB, METHOD_HUB, None),
    (DATA_CONNECTED, METHOD_CONNECTED, None),
    (DATA_IO, METHOD_IO, IO_READ_PARAMS),
    (DATA_SELFCHECK, METHOD_SELFCHECK, None),
    (DATA_UPGRADE, METHOD_UPGRADE, None),
)

# Configuration reads, refreshed every SLOW_EVERY cycles.
_SLOW_CALLS: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    (DATA_WLAN, METHOD_WLAN, None),
    (DATA_APN, METHOD_APN, None),
    (DATA_LAN, METHOD_LAN, LAN_READ_PARAMS),
)


# Distinct from None, which is a legitimate "the report carried no counter".
_UNSEEN: Final = object()

_TICK_FIELDS: Final = (
    "snrLastUpdateTimeMs",
    "isTrackedLastUpdateTimeMs",
    "isUsedInFixLastUpdateTimeMs",
    "elevationLastUpdateTimeMs",
)


def _module_tick(report: dict[str, Any]) -> int | None:
    """The receiver's observation counter, or None if the report lacks one.

    Every satellite entry carries the same value; the newest is taken so a
    single malformed entry cannot hold the counter back.
    """
    sats = (report.get("gnss") or {}).get("SatsInView")
    if not isinstance(sats, list):
        return None
    ticks: list[int] = []
    for sat in sats:
        if not isinstance(sat, dict):
            continue
        # All four carry the same value; reading every one means a satellite
        # that stops reporting SNR cannot hold the counter back on its own.
        for field in _TICK_FIELDS:
            try:
                ticks.append(int(sat[field]))
            except KeyError, TypeError, ValueError:
                continue
    return max(ticks) if ticks else None


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
        self._cycle = 0
        # Last-known config reads, carried forward between slow refreshes.
        self._slow: dict[str, Any] = {key: None for key, _m, _p in _SLOW_CALLS}
        # Last good GNSS report, carried forward when a poll comes back empty.
        self._gnss: dict[str, Any] | None = None
        # Liveness is judged from the receiver's own observation counter rather
        # than the report's timestamp. The timestamp is stamped when the reply
        # is composed, so it advances even when the position behind it does
        # not; the counter only moves when the receiver produces a new
        # observation. Age is then measured from when that counter was last
        # seen to change locally, which needs no comparison between the
        # router's clock and ours.
        self._gnss_tick: Any = _UNSEEN
        self._gnss_tick_at: float = 0.0
        # When a report was last read at all. The counter clock above can only
        # age a report that carried a counter, so this one bounds every other
        # case: without it a report lacking a counter would be republished
        # unchanged for as long as reads kept failing.
        self._gnss_at: float = 0.0
        # Smallest observed difference between our clock and the receiver's
        # counter, i.e. the least-delayed reply seen so far. Differencing two
        # monotonic clocks leaves a constant offset, so this calibrates it
        # without ever comparing the router's wall clock to ours.
        self._tick_offset: float | None = None

    async def _fetch_gnss(self) -> dict[str, Any] | None:
        """Read the GNSS endpoint once, or None if the read fails.

        Retried only when the request never reached the service. Replies carry
        no request identifier, so a request that was accepted and then timed
        out leaves its reply waiting for whoever asks next: retrying that
        collects the stale reply rather than a fresh one and leaves its own
        behind, doubling the cycle's exposure to whatever created the offset.
        A refused connection leaves nothing behind, so it costs nothing to try
        again. Anything still failing is carried forward.
        """
        for attempt in (1, 2):
            try:
                return await self.api.get_gnss()
            except YsUnreachableError as exc:
                _LOGGER.debug("GNSS unreachable (attempt %d): %s", attempt, exc)
            except YsError as exc:
                _LOGGER.debug("GNSS read failed: %s", exc)
                return None
        return None

    def _merge_gnss(self, fresh: dict[str, Any] | None) -> dict[str, Any] | None:
        """Attach a locally-measured fix age, carrying forward on failure."""
        now = self.hass.loop.time()
        if fresh is not None:
            self._gnss = fresh
            self._gnss_at = now
            tick = _module_tick(fresh)
            # A report that has lost its counter says nothing about liveness,
            # so it must not restart the counter clock -- otherwise a single
            # degraded report un-blanks a position that was about to expire.
            if tick is not None:
                offset = now - tick / 1000.0
                if self._tick_offset is None or offset < self._tick_offset:
                    self._tick_offset = offset
                if tick != self._gnss_tick:
                    self._gnss_tick = tick
                    self._gnss_tick_at = now
        if self._gnss is None:
            return None
        seen = self._gnss_tick is not _UNSEEN and self._gnss_tick is not None
        return {
            **self._gnss,
            # Counter stopped moving: the receiver has stalled.
            "fix_age": (now - self._gnss_tick_at) if seen else None,
            # Nothing read at all: the report is simply old. Always a number,
            # so carrying a report forward can never be unbounded.
            "report_age": now - self._gnss_at,
            # How far behind the observation itself is, which is the only one
            # of the three that catches replies served from a backlog: those
            # carry a counter that advances every poll and so look fresh.
            "observation_lag": (
                (now - self._gnss_tick / 1000.0) - self._tick_offset
                if seen and self._tick_offset is not None
                else None
            ),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        # Log in once up front so the concurrent calls below share the session.
        try:
            await self.api.login()
        except YsAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except YsError as exc:
            raise UpdateFailed(str(exc)) from exc

        # Refresh the config reads on the first cycle and every SLOW_EVERY after.
        slow_due = self._cycle % SLOW_EVERY == 0
        self._cycle += 1
        calls = (*_CALLS, *_SLOW_CALLS) if slow_due else _CALLS

        # The GNSS endpoint is a different service on a different port, so it
        # runs alongside the RPC batch rather than after it: its retry must not
        # add its wait to the cycle time.
        results, gnss = await asyncio.gather(
            asyncio.gather(
                *(self.api.call(method, params) for _key, method, params in calls),
                return_exceptions=True,
            ),
            self._fetch_gnss(),
        )

        data: dict[str, Any] = {}
        auth_failures = 0
        failures = 0
        for (key, method, _params), res in zip(calls, results):
            slow = key in self._slow
            if isinstance(res, Exception):
                if isinstance(res, YsAuthError):
                    auth_failures += 1
                else:
                    _LOGGER.debug("%s failed: %s", method, res)
                if not slow:
                    failures += 1
                # A failed config read keeps its previous value rather than
                # blanking entities that describe settings which haven't changed.
                data[key] = self._slow[key] if slow else None
            else:
                data[key] = res
                if slow:
                    self._slow[key] = res

        # Carry forward any config read not due this cycle.
        for key, value in self._slow.items():
            data.setdefault(key, value)

        if auth_failures == len(calls):
            raise ConfigEntryAuthFailed("router rejected the session on every call")
        # A cycle where every live call failed (but not all on auth) is a full
        # data loss -- fail the update so entities go unavailable rather than
        # showing a stale/blank state as if the poll had succeeded.
        if failures == len(_CALLS):
            raise UpdateFailed("router returned no data on any call")

        data[DATA_THROUGHPUT] = self._throughput(data.get(DATA_MOBILE))
        # Deliberately outside the failure accounting above: this endpoint is
        # independent of the RPC session, so losing it is not a router-wide
        # failure and must not fail the whole update.
        data[DATA_GNSS] = self._merge_gnss(gnss)
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
