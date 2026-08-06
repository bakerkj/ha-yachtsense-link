# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Async client for the Raymarine YachtSense Link router web API.

The router runs a GoAhead web server: a form ``POST /action/login`` yields a
session cookie, then everything is served through a single JSON-RPC endpoint
``POST /action/action``. Sessions expire (error code -99), so calls re-login
once and retry.

Newer firmware (V142.242.530 and later) serves the web API over HTTPS only and
302-redirects every plain-HTTP path to Raymarine's cloud portal, so the scheme
is probed on first use and the working one cached. TLS is not verified: the
router presents a ``CN=yachtsense.raymarine.com`` certificate signed by a
private Raymarine CA, which matches neither the LAN IP it is reached on nor any
public trust root.

Position comes from a separate service: the router answers unauthenticated plain
HTTP on port 9999 with fix type, DOP, per-satellite detail, and a timestamp that
tracks the fix rather than the request. That timestamp is what makes a fix which
has stopped updating detectable, so it is the only position source.

That endpoint intermittently answers 503 ``{"state": false}`` instead of a fix.
It means "no data this instant", not "no fix", so a failure is retried once and
otherwise carried forward rather than blanking the position.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .const import GNSS_PATH, GNSS_PORT, GNSS_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# Router-side auth-expiry RPC error code.
_AUTH_EXPIRED_CODE = -99

# After a failed login, coalesce further login attempts for this long so a burst
# of concurrent expired calls doesn't fire multiple credential posts (which trips
# the router's login rate-limiter). Kept well under the minimum poll interval so
# the next cycle still retries.
_LOGIN_RETRY_COOLDOWN = 5.0


class YsError(Exception):
    """The router could not be reached or returned something unusable."""


class YsAuthError(YsError):
    """The router rejected our credentials or session."""


class YsLockoutError(YsAuthError):
    """The router is rate-limiting logins; back off before retrying."""


def new_cookie_jar() -> aiohttp.CookieJar:
    """A cookie jar that keeps cookies for a bare-IP host.

    aiohttp's default jar silently drops cookies for IP-address hosts, which
    would break the router's session entirely.
    """
    return aiohttp.CookieJar(unsafe=True)


class YachtSenseLinkApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        timeout: float = 10.0,
    ) -> None:
        self._session = session
        self._host = host
        self._scheme: str | None = None
        self._user = username
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._logged_in = False
        self._login_lock = asyncio.Lock()
        self._last_login_error: YsError | None = None
        self._last_login_at = 0.0

    @property
    def _base(self) -> str:
        return f"{self._scheme or 'https'}://{self._host}"

    async def aclose(self) -> None:
        """Close the underlying HTTP session."""
        await self._session.close()

    async def login(self) -> None:
        if self._logged_in:
            return
        # Serialize logins so concurrent calls don't fire multiple credential
        # posts (which would trip the router's login rate-limiter).
        async with self._login_lock:
            if self._logged_in:
                return
            # Coalesce a burst of concurrent re-logins after a failure: the six
            # gathered RPCs can all hit an expired session at once. The first
            # attempt posts; the rest re-raise the cached error until a short
            # cooldown passes, so we never hammer the router's login endpoint.
            if (
                self._last_login_error is not None
                and time.monotonic() - self._last_login_at < _LOGIN_RETRY_COOLDOWN
            ):
                raise self._last_login_error
            try:
                await self._do_login()
            except YsError as exc:
                self._last_login_error = exc
                self._last_login_at = time.monotonic()
                raise
            self._last_login_error = None

    async def _probe_scheme(self) -> str:
        """Return the scheme the router's own web API answers on.

        A scheme counts as working only if it serves ``/index.html`` itself. A
        redirect means it doesn't: newer firmware bounces every plain-HTTP path
        to Raymarine's cloud portal, and following that would send the login
        POST to the internet instead of the router. A same-host redirect that
        only upgrades the scheme is likewise a "use the other one" signal, not
        an endorsement of the scheme that issued it -- the loop tries the other
        scheme on its own, so there is nothing to chase here.
        """
        host = urlsplit(f"//{self._host}").hostname
        errors: list[str] = []
        for scheme in ("https", "http"):
            try:
                async with self._session.get(
                    f"{scheme}://{self._host}/index.html",
                    timeout=self._timeout,
                    ssl=False,
                    allow_redirects=False,
                ) as resp:
                    if 300 <= resp.status < 400:
                        location = resp.headers.get("Location", "")
                        loc = urlsplit(location)
                        # A relative Location keeps both host and scheme.
                        same_host = not loc.hostname or loc.hostname == host
                        if not same_host or loc.scheme not in ("", scheme):
                            errors.append(f"{scheme}: redirects to {location}")
                            continue
                    return scheme
            except aiohttp.ClientError as exc:
                errors.append(f"{scheme}: {exc}")
        raise YsError(f"router not reachable ({'; '.join(errors)})")

    async def _do_login(self) -> None:
        # Prime the session cookie, then post credentials (plaintext, form-encoded;
        # the router does no client-side hashing for login).
        try:
            if self._scheme is None:
                self._scheme = await self._probe_scheme()
                _LOGGER.debug("Using %s for %s", self._scheme, self._host)
            async with self._session.get(
                f"{self._base}/index.html", timeout=self._timeout, ssl=False
            ):
                pass
            async with self._session.post(
                f"{self._base}/action/login",
                data={
                    "username": self._user,
                    "password": self._password,
                    "login_mode": "Active",
                },
                headers={"Time-Stamp": str(int(time.time() * 1000)), "Time-Zone": "0"},
                timeout=self._timeout,
                ssl=False,
            ) as resp:
                doc = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise YsError(f"login request failed: {exc}") from exc
        except ValueError as exc:
            raise YsAuthError(f"unexpected login response: {exc}") from exc

        res = doc.get("result", {}) if isinstance(doc, dict) else {}
        if str(res.get("login")) != "1":
            left = res.get("left_seconds")
            if left and str(left) != "0":
                raise YsLockoutError(
                    f"login rate-limited: {res.get('try_times')} tries left, "
                    f"wait {left}s"
                )
            raise YsAuthError("router rejected credentials (check username/password)")
        self._logged_in = True
        _LOGGER.debug("Authenticated to YachtSense Link at %s", self._base)

    async def get_gnss(self) -> dict[str, Any]:
        """Return the router's detailed GNSS report, or raise YsError.

        Plain HTTP on a fixed port, taking no session and no credentials, so
        this deliberately bypasses login() and the RPC endpoint. A 503 carries a
        JSON body with ``state: false``; that is treated the same as a transport
        error, leaving the caller to retry and then carry forward.
        """
        host = urlsplit(f"//{self._host}").hostname or self._host
        url = f"http://{host}:{GNSS_PORT}{GNSS_PATH}"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=GNSS_TIMEOUT)
            ) as resp:
                doc = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise YsError(f"gnss: request failed: {exc}") from exc
        except TimeoutError as exc:
            raise YsError("gnss: request timed out") from exc
        except ValueError as exc:
            raise YsError(f"gnss: invalid JSON: {exc}") from exc

        if not isinstance(doc, dict) or not doc.get("state") or "gnss" not in doc:
            err = doc.get("error") if isinstance(doc, dict) else None
            raise YsError(f"gnss: no data ({err or 'unexpected response'})")
        return doc

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not self._logged_in:
            await self.login()
        try:
            return await self._rpc(method, params)
        except YsAuthError:
            _LOGGER.debug("Session expired; re-authenticating")
            self._logged_in = False
            await self.login()
            return await self._rpc(method, params)

    async def _rpc(self, method: str, params: dict[str, Any] | None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": "1",
        }
        try:
            async with self._session.post(
                f"{self._base}/action/action",
                json=payload,
                timeout=self._timeout,
                ssl=False,
            ) as resp:
                doc = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise YsError(f"{method}: request failed: {exc}") from exc
        except ValueError as exc:
            raise YsError(f"{method}: invalid JSON: {exc}") from exc

        if isinstance(doc, dict) and doc.get("error"):
            err = doc["error"]
            # Usually an object; guard against a bare string/bool so a real error
            # is surfaced as YsError rather than mis-read as auth-expiry / code 0.
            if isinstance(err, dict):
                raw = err.get("code")
                try:
                    code = int(raw) if isinstance(raw, (int, str)) else 0
                except ValueError:
                    code = 0
                if code == _AUTH_EXPIRED_CODE:
                    raise YsAuthError(f"{method}: session expired")
            raise YsError(f"{method}: RPC error {err}")
        return doc.get("result") if isinstance(doc, dict) else None
