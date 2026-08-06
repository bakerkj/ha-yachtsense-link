# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Coordinator tests: merge, partial failure, auth failure, throughput."""

import datetime

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.yachtsense_link.api import (
    YsAuthError,
    YsError,
    YsUnreachableError,
)
from custom_components.yachtsense_link.const import (
    DATA_GNSS,
    DATA_HOME,
    DATA_HUB,
    DATA_LAN,
    DATA_MOBILE,
    DATA_THROUGHPUT,
    SLOW_EVERY,
)
from custom_components.yachtsense_link.coordinator import YachtSenseLinkCoordinator

from .fixtures import GNSS, responses

_UNSET = object()


class FakeApi:
    def __init__(
        self,
        resp,
        fail_auth=(),
        fail_err=(),
        login_error=None,
        gnss=_UNSET,
        gnss_fail=0,
        gnss_error=None,
    ):
        self.resp = resp
        self.fail_auth = set(fail_auth)
        self.fail_err = set(fail_err)
        self.login_error = login_error
        self.gnss = GNSS if gnss is _UNSET else gnss
        # Number of leading get_gnss() calls that raise, to exercise the retry.
        self.gnss_fail = gnss_fail
        self.gnss_error = gnss_error
        self.gnss_calls = 0

    async def login(self):
        if self.login_error is not None:
            raise self.login_error

    async def get_gnss(self):
        self.gnss_calls += 1
        if self.gnss_calls <= self.gnss_fail or self.gnss is None:
            raise (self.gnss_error or YsError)("gnss: no data")
        return self.gnss

    async def call(self, method, params=None):
        if method in self.fail_auth:
            raise YsAuthError(method)
        if method in self.fail_err:
            raise YsError(method)
        return self.resp[method]


async def test_merges_all_methods(hass):
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    data = await coord._async_update_data()
    assert data[DATA_HOME]["ap"]["name"] == "TestAP"
    assert data[DATA_MOBILE]["sim"][0]["current_data_used"] == 4270
    assert data[DATA_THROUGHPUT]["rate_mb_per_h"] == 0.0  # first sample, no prior


async def test_partial_failure_degrades(hass):
    coord = YachtSenseLinkCoordinator(
        hass, FakeApi(responses(), fail_err=["GetHubInfo"]), 60
    )
    data = await coord._async_update_data()
    assert data[DATA_HUB] is None
    assert data[DATA_HOME] is not None


async def test_all_auth_failures_raise(hass):
    coord = YachtSenseLinkCoordinator(
        hass, FakeApi(responses(), fail_auth=list(responses())), 60
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()


async def test_login_error_raises_update_failed(hass):
    coord = YachtSenseLinkCoordinator(
        hass, FakeApi(responses(), login_error=YsError("router down")), 60
    )
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_mixed_auth_failure_degrades(hass):
    # Some (not all) calls auth-fail -> degrade, do not raise.
    coord = YachtSenseLinkCoordinator(
        hass, FakeApi(responses(), fail_auth=["GetHomeStatus"]), 60
    )
    data = await coord._async_update_data()
    assert data[DATA_HOME] is None
    assert data[DATA_HUB] is not None


async def test_full_non_auth_failure_raises_update_failed(hass):
    # Every call fails (non-auth) -> full data loss -> fail the update so
    # entities go unavailable rather than showing blank state.
    coord = YachtSenseLinkCoordinator(
        hass, FakeApi(responses(), fail_err=list(responses())), 60
    )
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


def test_throughput_math(hass, monkeypatch):
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    now = [datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC)]
    monkeypatch.setattr(
        "custom_components.yachtsense_link.coordinator.dt_util.utcnow",
        lambda: now[0],
    )
    first = coord._throughput({"active_sim": 0, "sim": [{"current_data_used": 100}]})
    assert first["rate_mb_per_h"] == 0.0

    now[0] += datetime.timedelta(seconds=60)  # +60s, +3 MB -> 180 MB/h
    second = coord._throughput({"active_sim": 0, "sim": [{"current_data_used": 103}]})
    assert second["rate_mb_per_h"] == 180.0


def test_throughput_reset_is_not_negative(hass, monkeypatch):
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    now = [datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC)]
    monkeypatch.setattr(
        "custom_components.yachtsense_link.coordinator.dt_util.utcnow",
        lambda: now[0],
    )
    coord._throughput({"active_sim": 0, "sim": [{"current_data_used": 4000}]})
    now[0] += datetime.timedelta(seconds=60)
    after = coord._throughput({"active_sim": 0, "sim": [{"current_data_used": 5}]})
    assert after["rate_mb_per_h"] == 0.0


async def test_config_reads_are_polled_slowly_and_carried_forward(hass):
    # Config methods are read on the first cycle, then carried forward until
    # SLOW_EVERY cycles have passed -- an embedded router shouldn't field
    # eleven concurrent RPCs a minute to re-read static settings.
    class CountingApi(FakeApi):
        def __init__(self, resp):
            super().__init__(resp)
            self.calls = []

        async def call(self, method, params=None):
            self.calls.append(method)
            return await super().call(method, params)

    api = CountingApi(responses())
    coord = YachtSenseLinkCoordinator(hass, api, 60)

    first = await coord._async_update_data()
    assert api.calls.count("GetWlanSettings") == 1
    assert first[DATA_LAN]["ip_1"] == "192.0.2.170"

    second = await coord._async_update_data()
    assert api.calls.count("GetWlanSettings") == 1  # not re-read
    assert second[DATA_LAN]["ip_1"] == "192.0.2.170"  # still available

    for _ in range(SLOW_EVERY - 2):
        await coord._async_update_data()
    await coord._async_update_data()
    assert api.calls.count("GetWlanSettings") == 2  # refreshed on schedule


async def test_failed_config_read_keeps_last_known_value(hass):
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    good = await coord._async_update_data()
    assert good[DATA_LAN] is not None

    coord.api = FakeApi(responses(), fail_err=["LanConfigure"])
    for _ in range(SLOW_EVERY):
        data = await coord._async_update_data()
    # The live calls still succeeded, so the LAN settings stay at last-known
    # rather than blanking entities that describe unchanged configuration.
    assert data[DATA_LAN]["ip_1"] == "192.0.2.170"


async def test_gnss_is_merged_with_a_fix_age(hass):
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    data = await coord._async_update_data()
    assert data[DATA_GNSS]["gnss"]["Latitude"] == "43.05803298950195"
    assert data[DATA_GNSS]["fix_age"] >= 0


async def test_gnss_is_read_exactly_once_per_cycle(hass):
    # A second read would collect the first request's buffered reply rather
    # than fresh data, and leave its own for the next cycle.
    api = FakeApi(responses())
    coord = YachtSenseLinkCoordinator(hass, api, 60)
    await coord._async_update_data()
    assert api.gnss_calls == 1


async def test_a_failed_gnss_read_is_not_retried(hass):
    api = FakeApi(responses(), gnss=None)
    coord = YachtSenseLinkCoordinator(hass, api, 60)
    data = await coord._async_update_data()
    assert api.gnss_calls == 1  # one read, then wait for the next cycle
    assert data[DATA_GNSS] is None


async def test_gnss_loss_does_not_fail_the_whole_update(hass):
    # The endpoint is a separate service; losing it must not blank the RPC data.
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses(), gnss=None), 60)
    data = await coord._async_update_data()
    assert data[DATA_GNSS] is None
    assert data[DATA_HOME] is not None


async def test_gnss_is_carried_forward_but_ages(hass):
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    await coord._async_update_data()

    # Pretend the last good fix was seen a while ago, then lose the endpoint.
    coord._gnss_tick_at -= 120.0
    coord.api = FakeApi(responses(), gnss=None)
    data = await coord._async_update_data()
    # The position is still there, but it is no longer claiming to be fresh.
    assert data[DATA_GNSS]["gnss"]["Fix"] == "2"
    assert data[DATA_GNSS]["fix_age"] >= 120.0


async def test_unchanged_counter_keeps_ageing(hass):
    # A stalled receiver answers every poll happily, with a freshly stamped
    # reply wrapped around an unchanged observation counter; the age must keep
    # climbing rather than resetting on each successful read.
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    await coord._async_update_data()
    coord._gnss_tick_at -= 200.0
    data = await coord._async_update_data()
    assert data[DATA_GNSS]["fix_age"] >= 200.0


async def test_a_new_counter_resets_the_age(hass):
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    await coord._async_update_data()
    coord._gnss_tick_at -= 200.0

    moved = {
        **GNSS,
        "gnss": {
            **GNSS["gnss"],
            "SatsInView": [
                {**s, "snrLastUpdateTimeMs": "93999999"}
                for s in GNSS["gnss"]["SatsInView"]
            ],
        },
    }
    coord.api = FakeApi(responses(), gnss=moved)
    data = await coord._async_update_data()
    assert data[DATA_GNSS]["fix_age"] < 10.0


async def test_a_fresh_timestamp_does_not_hide_a_stalled_receiver(hass):
    # The report's timestamp is stamped when the reply is composed, so it keeps
    # advancing even while the position behind it is frozen. Liveness must come
    # from the observation counter alone, or a stalled receiver reads as live.
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    await coord._async_update_data()
    coord._gnss_tick_at -= 200.0

    restamped = {**GNSS, "timestamp": "2026-08-06T09:99:99Z"}
    coord.api = FakeApi(responses(), gnss=restamped)
    data = await coord._async_update_data()
    assert data[DATA_GNSS]["fix_age"] >= 200.0


async def test_a_report_without_a_counter_does_not_blank_forever(hass):
    # No counter means liveness is unknown, not stale. Reporting an age here
    # would blank the position permanently on the very first poll.
    stripped = {**GNSS, "gnss": {**GNSS["gnss"], "SatsInView": []}}
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses(), gnss=stripped), 60)
    data = await coord._async_update_data()
    assert data[DATA_GNSS]["fix_age"] is None


async def test_a_counterless_report_is_not_carried_forward_forever(hass):
    # Without a counter there is no liveness clock, so nothing would ever age
    # the report out. Repeated failed reads must still expire it.
    stripped = {**GNSS, "gnss": {**GNSS["gnss"], "SatsInView": []}}
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses(), gnss=stripped), 60)
    first = await coord._async_update_data()
    assert first[DATA_GNSS]["fix_age"] is None  # liveness unknown
    assert first[DATA_GNSS]["report_age"] >= 0.0

    coord._gnss_at -= 500.0
    coord.api = FakeApi(responses(), gnss=None)
    data = await coord._async_update_data()
    assert data[DATA_GNSS]["report_age"] >= 500.0


async def test_a_degraded_report_does_not_reset_an_expiring_fix(hass):
    # A report that has lost its counter says nothing about liveness; letting
    # it restart the clock would un-blank a position about to expire.
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    await coord._async_update_data()
    coord._gnss_tick_at -= 80.0

    stripped = {**GNSS, "gnss": {**GNSS["gnss"], "SatsInView": []}}
    coord.api = FakeApi(responses(), gnss=stripped)
    data = await coord._async_update_data()
    assert data[DATA_GNSS]["fix_age"] >= 80.0  # kept ageing, not reset


async def test_backlogged_replies_are_caught_by_observation_lag(hass):
    # A steady backlog hands back replies whose counter advances every poll, so
    # they look fresh by every other measure. Only the gap between the counter
    # and our own clock reveals that the observation itself is old.
    coord = YachtSenseLinkCoordinator(hass, FakeApi(responses()), 60)
    first = await coord._async_update_data()
    assert first[DATA_GNSS]["observation_lag"] == pytest.approx(0.0, abs=1.0)

    # Counter advanced, but by far less than the wall-clock time that passed.
    coord._tick_offset -= 300.0
    behind = {
        **GNSS,
        "gnss": {
            **GNSS["gnss"],
            "SatsInView": [
                {**s, "snrLastUpdateTimeMs": "93024211"}
                for s in GNSS["gnss"]["SatsInView"]
            ],
        },
    }
    coord.api = FakeApi(responses(), gnss=behind)
    data = await coord._async_update_data()
    assert data[DATA_GNSS]["observation_lag"] >= 290.0


async def test_an_unreachable_gnss_read_is_retried(hass):
    # Nothing reached the service, so no reply was generated and none was left
    # waiting for the next caller: trying again costs nothing.
    api = FakeApi(responses(), gnss_fail=1, gnss_error=YsUnreachableError)
    coord = YachtSenseLinkCoordinator(hass, api, 60)
    data = await coord._async_update_data()
    assert api.gnss_calls == 2
    assert data[DATA_GNSS]["gnss"]["Fix"] == "2"


async def test_a_timed_out_gnss_read_is_not_retried(hass):
    # The service took the request, so a reply is already owed to us; asking
    # again would collect that stale reply and leave another in its place.
    api = FakeApi(responses(), gnss_fail=1, gnss_error=YsError)
    coord = YachtSenseLinkCoordinator(hass, api, 60)
    await coord._async_update_data()
    assert api.gnss_calls == 1


async def test_unreachable_gives_up_after_two_attempts(hass):
    api = FakeApi(responses(), gnss=None, gnss_error=YsUnreachableError)
    coord = YachtSenseLinkCoordinator(hass, api, 60)
    data = await coord._async_update_data()
    assert api.gnss_calls == 2
    assert data[DATA_GNSS] is None
