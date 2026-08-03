# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Diagnostics for the YachtSense Link integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# async_redact_data matches keys exactly (case-sensitive) at any depth. The
# router returns the FULL raw RPC payload (coordinator.data isn't trimmed like the
# test fixtures), so this deny-list errs broad -- covering SIM/WiFi/device
# identifiers and their likely casing variants -- to avoid leaking anything a real
# modem returns beyond what the entities read.
TO_REDACT = {
    # Config-entry identifiers.
    "host",
    "username",
    "title",
    "password",
    "unique_id",
    # Hub / device identity.
    "IMEI",
    "imei",
    "serial_num",
    "serial",
    # SIM / cellular identity.
    "imsi",
    "IMSI",
    "iccid",
    "ICCID",
    "msisdn",
    "MSISDN",
    "phone",
    "number",
    "provider",
    "cell_id",
    "lac",
    "plmn",
    "plmn2",
    # Addresses.
    "ipv4address",
    "ipv4gw",
    "ipaddr",  # wan.ipaddr (WAN/uplink IP)
    "IPAddress",
    "MACAddress",
    "mac",
    # WiFi names: uplink SSID (sta.sta_ssid), the boat's own AP SSID (ap.name --
    # also redacts the harmless IO channel names), and generic ssid/bssid variants.
    "sta_ssid",
    "name",
    "ssid",
    "SSID",
    "bssid",
    "BSSID",
    # GPS position.
    "lat",
    "lng",
    # Connected-client hostnames.
    "DName",
    # Secrets returned by the config reads: GetWlanSettings hands back the AP's
    # pre-shared key in cleartext, GetAllApn the per-APN carrier credentials,
    # and GetGnssAuthToken a bearer token.
    "WpaKey",
    "wpakey",
    "WpaKey1",
    "Key",
    "key",
    "auth_token",
    # LAN/IPv6 addressing from LanConfigure.
    "ip_1",
    "ip_2",
    "gateway",
    "start_ip",
    "end_ip",
    "IPv6_Global_ID",
    "ipv6addr",
    "ipq_ipaddr",
    "Ssid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": async_redact_data(coordinator.data, TO_REDACT),
    }
