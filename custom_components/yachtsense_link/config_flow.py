# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Config flow for the YachtSense Link integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from .api import (
    YachtSenseLinkApi,
    YsAuthError,
    YsError,
    YsLockoutError,
    new_cookie_jar,
)
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_USERNAME,
    METHOD_HUB,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)
            ): str,
            vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL)),
        }
    )


def _reauth_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)
            ): str,
            vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
        }
    )


async def _validate(user_input: dict[str, Any]) -> str | None:
    """Log in and return the router serial (for unique_id). Raises on failure."""
    session = aiohttp.ClientSession(cookie_jar=new_cookie_jar())
    try:
        api = YachtSenseLinkApi(
            session,
            user_input[CONF_HOST],
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
        )
        await api.login()
        hub = await api.call(METHOD_HUB)
    finally:
        await session.close()
    if isinstance(hub, dict):
        return str(hub.get("serial_num") or hub.get("IMEI") or "").strip() or None
    return None


class YachtSenseLinkConfigFlow(config_entries.ConfigFlow, domain="yachtsense_link"):  # type: ignore[call-arg]
    """Config flow for YachtSense Link."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            serial, err = await self._try(user_input)
            if err:
                errors["base"] = err
            else:
                await self.async_set_unique_id(serial or user_input[CONF_HOST].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_HOST],
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options={
                        CONF_UPDATE_INTERVAL: user_input[CONF_UPDATE_INTERVAL],
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=_schema({}), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update connection settings and interval in place."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            serial, err = await self._try(user_input)
            if err:
                errors["base"] = err
            else:
                # Refuse to point this entry at a different router.
                await self.async_set_unique_id(serial or user_input[CONF_HOST].lower())
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options={CONF_UPDATE_INTERVAL: user_input[CONF_UPDATE_INTERVAL]},
                )
        defaults = {**entry.data, **entry.options}
        return self.async_show_form(
            step_id="reconfigure", data_schema=_schema(defaults), errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the router rejects the saved session."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for fresh credentials and update the entry in place."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            # Reauth only re-prompts credentials; host stays as configured.
            merged = {**entry.data, **user_input}
            serial, err = await self._try(merged)
            if err:
                errors["base"] = err
            else:
                # Refuse to accept credentials for a different router.
                await self.async_set_unique_id(serial or merged[CONF_HOST].lower())
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data=merged)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_reauth_schema(entry.data),
            description_placeholders={CONF_HOST: entry.data[CONF_HOST]},
            errors=errors,
        )

    async def _try(self, user_input: dict[str, Any]) -> tuple[str | None, str | None]:
        """Return (serial, error_key)."""
        try:
            return await _validate(user_input), None
        except YsLockoutError:
            return None, "rate_limited"
        except YsAuthError:
            return None, "invalid_auth"
        except YsError:
            return None, "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error validating YachtSense Link")
            return None, "unknown"
