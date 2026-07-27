# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Config-flow tests."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.yachtsense_link.api import YsAuthError, YsError, YsLockoutError
from custom_components.yachtsense_link.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

USER_INPUT = {
    CONF_HOST: "192.0.2.10",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_UPDATE_INTERVAL: 60,
}

_VALIDATE = "custom_components.yachtsense_link.config_flow._validate"
_SETUP = "custom_components.yachtsense_link.async_setup_entry"


def _entry(hass, password="old"):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="TESTSERIAL01",
        data={
            CONF_HOST: "192.0.2.10",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: password,
        },
        options={CONF_UPDATE_INTERVAL: 60},
    )
    entry.add_to_hass(hass)
    return entry


async def test_user_flow_success(hass):
    with (
        patch(
            "custom_components.yachtsense_link.config_flow._validate",
            return_value="TESTSERIAL01",
        ),
        patch("custom_components.yachtsense_link.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "192.0.2.10"
    assert result["data"][CONF_HOST] == "192.0.2.10"
    assert result["data"][CONF_PASSWORD] == "secret"
    assert result["options"][CONF_UPDATE_INTERVAL] == 60


async def test_user_flow_invalid_auth(hass):
    with patch(
        "custom_components.yachtsense_link.config_flow._validate",
        side_effect=YsAuthError(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_lockout(hass):
    with patch(
        "custom_components.yachtsense_link.config_flow._validate",
        side_effect=YsLockoutError(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "rate_limited"}


async def test_user_flow_cannot_connect(hass):
    with patch(_VALIDATE, side_effect=YsError()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown(hass):
    with patch(_VALIDATE, side_effect=RuntimeError("boom")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_duplicate_device_aborts(hass):
    _entry(hass)
    with patch(_VALIDATE, return_value="TESTSERIAL01"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_success(hass):
    entry = _entry(hass)
    with (
        patch(_VALIDATE, return_value="TESTSERIAL01"),
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**USER_INPUT, CONF_PASSWORD: "newpass", CONF_UPDATE_INTERVAL: 30},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PASSWORD] == "newpass"
    assert entry.options[CONF_UPDATE_INTERVAL] == 30


async def test_reconfigure_wrong_device_aborts(hass):
    entry = _entry(hass)
    with patch(_VALIDATE, return_value="OTHERSERIAL"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"


async def test_reauth_flow_success(hass):
    entry = _entry(hass, password="old")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    with (
        patch(_VALIDATE, return_value="TESTSERIAL01"),
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "admin", CONF_PASSWORD: "newpass"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "newpass"


async def test_reauth_flow_wrong_device_aborts(hass):
    entry = _entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    with patch(_VALIDATE, return_value="OTHERSERIAL"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "admin", CONF_PASSWORD: "newpass"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
