# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Coordinator tests: merge, partial failure, auth failure, throughput."""

import datetime

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.yachtsense_link.api import YsAuthError, YsError
from custom_components.yachtsense_link.const import (
    DATA_HOME,
    DATA_HUB,
    DATA_MOBILE,
    DATA_THROUGHPUT,
)
from custom_components.yachtsense_link.coordinator import YachtSenseLinkCoordinator

from .fixtures import responses


class FakeApi:
    def __init__(self, resp, fail_auth=(), fail_err=(), login_error=None):
        self.resp = resp
        self.fail_auth = set(fail_auth)
        self.fail_err = set(fail_err)
        self.login_error = login_error

    async def login(self):
        if self.login_error is not None:
            raise self.login_error
        return None

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
