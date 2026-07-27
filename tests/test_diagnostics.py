# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Diagnostics redaction tests."""

import json
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.yachtsense_link.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)
from custom_components.yachtsense_link.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .fixtures import CONNECTED, GPS, HOME, HUB


async def test_diagnostics_redacts_sensitive_fields(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="192.0.2.10",
        unique_id="TESTSERIAL01",
        data={
            CONF_HOST: "192.0.2.10",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "secret",
        },
        options={CONF_UPDATE_INTERVAL: 60},
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        data={"home": HOME, "connected": CONNECTED, "hub": HUB, "gps": GPS}
    )

    diag = await async_get_config_entry_diagnostics(hass, entry)
    blob = json.dumps(diag)

    # None of these identifiable values may survive into a diagnostics upload.
    for secret in (
        "secret",  # password
        "TESTSERIAL01",  # serial_num + unique_id
        "000000000000000",  # IMEI
        "TestAP",  # ap.name (boat's own SSID)
        "test-client-1",  # connected-device hostname (DName)
        "192.0.2.10",  # host / entry title
        "TestCarrier",  # cellular provider
    ):
        assert secret not in blob, f"unredacted: {secret}"
    assert "**REDACTED**" in blob

    # ...but non-sensitive diagnostic data must survive (guard over-redaction).
    assert "YachtSense Link router" in blob  # hub Model
    assert "13.1" in blob  # hub Voltage
