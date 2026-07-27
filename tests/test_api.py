# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Direct tests for the YachtSenseLinkApi protocol glue.

The coordinator/config-flow tests fake the API; these exercise the real client
against a fake aiohttp session: login handling, the session-expiry retry, RPC
error mapping, and the re-login coalescing that protects the rate-limiter.
"""

import asyncio

import aiohttp
import pytest

from custom_components.yachtsense_link.api import (
    YachtSenseLinkApi,
    YsAuthError,
    YsError,
    YsLockoutError,
)

LOGIN_OK = {"result": {"login": "1"}}
LOGIN_REJECT = {"result": {"login": "0"}}
LOGIN_LOCKOUT = {"result": {"login": "0", "left_seconds": 30, "try_times": 2}}


class _Resp:
    """Async-context-manager stand-in for an aiohttp response."""

    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Programmable fake aiohttp ClientSession for the router API."""

    def __init__(self, *, login=LOGIN_OK, rpc=None):
        # login: payload dict, or an Exception to raise from json()
        # rpc: {method: payload | Exception | [payload, ...] queue}
        self._login = login
        self._rpc = rpc or {}
        self.login_posts = 0
        self.rpc_posts: list[str] = []
        self.last_login_data: dict | None = None
        self.last_login_headers: dict | None = None
        self.closed = False

    def get(self, url, timeout=None):
        return _Resp({})

    def post(self, url, data=None, json=None, headers=None, timeout=None):
        if url.endswith("/action/login"):
            self.login_posts += 1
            self.last_login_data = data
            self.last_login_headers = headers
            return _Resp(self._login)
        method = json["method"]
        self.rpc_posts.append(method)
        spec = self._rpc.get(method, {"result": {}})
        if isinstance(spec, list):
            spec = spec.pop(0)
        return _Resp(spec)

    async def close(self):
        self.closed = True


def _api(session):
    return YachtSenseLinkApi(session, "192.0.2.10", "admin", "secret")


async def test_login_success_sets_state():
    session = FakeSession()
    api = _api(session)
    await api.login()
    assert session.login_posts == 1
    # The credential post carries the expected form fields and timestamp headers.
    assert session.last_login_data == {
        "username": "admin",
        "password": "secret",
        "login_mode": "Active",
    }
    assert "Time-Stamp" in session.last_login_headers
    assert session.last_login_headers.get("Time-Zone") == "0"
    # Already logged in -> no second credential post.
    await api.login()
    assert session.login_posts == 1


async def test_login_rejected_raises_auth():
    api = _api(FakeSession(login=LOGIN_REJECT))
    with pytest.raises(YsAuthError):
        await api.login()


async def test_login_lockout_raises_lockout():
    api = _api(FakeSession(login=LOGIN_LOCKOUT))
    with pytest.raises(YsLockoutError):
        await api.login()


async def test_login_network_error_raises_yserror():
    api = _api(FakeSession(login=aiohttp.ClientError("boom")))
    with pytest.raises(YsError):
        await api.login()


async def test_call_returns_result():
    session = FakeSession(rpc={"GetHubInfo": {"result": {"serial_num": "X"}}})
    api = _api(session)
    assert await api.call("GetHubInfo") == {"serial_num": "X"}


async def test_session_expiry_retries_once():
    # First RPC reports expiry (-99); the client re-logs-in and retries.
    session = FakeSession(
        rpc={"GetHubInfo": [{"error": {"code": -99}}, {"result": {"ok": 1}}]}
    )
    api = _api(session)
    assert await api.call("GetHubInfo") == {"ok": 1}
    assert session.login_posts == 2  # initial + re-login
    assert session.rpc_posts == ["GetHubInfo", "GetHubInfo"]


async def test_rpc_error_raises_yserror():
    session = FakeSession(rpc={"GetHubInfo": {"error": {"code": 7, "msg": "nope"}}})
    with pytest.raises(YsError):
        await _api(session).call("GetHubInfo")


async def test_rpc_non_dict_error_is_yserror_not_attributeerror():
    # A bare-string/bool error field must map to YsError, not AttributeError.
    session = FakeSession(rpc={"GetHubInfo": {"error": "kaboom"}})
    with pytest.raises(YsError):
        await _api(session).call("GetHubInfo")


async def test_rpc_invalid_json_raises_yserror():
    session = FakeSession(rpc={"GetHubInfo": ValueError("not json")})
    with pytest.raises(YsError):
        await _api(session).call("GetHubInfo")


async def test_concurrent_failed_logins_are_coalesced():
    # Six gathered calls hitting a rejected login must fire ONE credential post,
    # not six (which would trip the router's login rate-limiter).
    session = FakeSession(login=LOGIN_REJECT)
    api = _api(session)
    results = await asyncio.gather(
        *(api.call("GetHubInfo") for _ in range(6)), return_exceptions=True
    )
    assert all(isinstance(r, YsAuthError) for r in results)
    assert session.login_posts == 1
