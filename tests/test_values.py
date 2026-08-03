# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Value-function tests: RPC data -> entity state, no HA runtime needed."""

import pytest

from custom_components.yachtsense_link.binary_sensor import (
    BINARY_SENSORS,
    IO_SWITCH_SENSORS,
)
from custom_components.yachtsense_link.const import (
    DATA_APN,
    DATA_CONNECTED,
    DATA_GPS,
    DATA_HOME,
    DATA_HUB,
    DATA_IO,
    DATA_LAN,
    DATA_MOBILE,
    DATA_SELFCHECK,
    DATA_THROUGHPUT,
    DATA_UPGRADE,
    DATA_WLAN,
)
from custom_components.yachtsense_link.sensor import IO_VOLTAGE_SENSORS, SENSORS

from .fixtures import (
    APN,
    CONNECTED,
    GPS,
    HOME,
    HUB,
    IO,
    LAN,
    MOBILE,
    SELFCHECK,
    UPGRADE,
    WLAN,
)


def _merged() -> dict:
    return {
        DATA_HOME: HOME,
        DATA_MOBILE: MOBILE,
        DATA_HUB: HUB,
        DATA_CONNECTED: CONNECTED,
        DATA_GPS: GPS,
        DATA_IO: IO,
        DATA_SELFCHECK: SELFCHECK,
        DATA_UPGRADE: UPGRADE,
        DATA_WLAN: WLAN,
        DATA_APN: APN,
        DATA_LAN: LAN,
        DATA_THROUGHPUT: {"rate_mb_per_h": 123.4},
    }


def _sensors() -> dict:
    return {d.key: d for d in (*SENSORS, *IO_VOLTAGE_SENSORS)}


def _binaries() -> dict:
    return {d.key: d for d in (*BINARY_SENSORS, *IO_SWITCH_SENSORS)}


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("cellular_signal", 94),  # csq 29/31 -> 94%
        ("cellular_rsrp", -84.0),
        ("cellular_provider", "TestCarrier"),
        ("cellular_band", "LTE BAND 4"),
        ("cellular_data_used", 4270.0),
        ("cellular_data_limit", 3072.0),
        ("cellular_data_remaining", -1198.0),  # over the plan cap
        ("cellular_data_used_pct", 139.0),
        ("cellular_days_left", 23),
        ("cellular_data_today", 218.0),
        ("cellular_throughput", 123.4),
        ("hub_voltage", 13.1),
        ("hub_current", 0.458),
        ("hub_signal", -55.0),
        ("hub_model", "YachtSense Link router"),
        ("hub_serial", "TESTSERIAL01"),
        ("net_wifi_ap_ssid", "TestAP"),
        ("net_wifi_uplink_ssid", None),  # sta_ssid is "-"
        ("net_wifi_clients", 0),
        ("net_clients", 2),
        ("io_ch1_voltage", 12.5),
        ("io_ch4_voltage", None),  # channel disabled
        # --- added for firmware V142.242.530 ---
        ("cellular_sim_slot", 1),  # active_sim 0 -> slot 1
        ("cellular_apn", "test.apn"),  # selected profile for the active SIM
        ("cellular_cell_id", "C4C7021"),
        ("cellular_lac", "55F3"),
        ("cellular_gateway", "192.0.2.254"),
        ("cellular_cycle_reset_day", 17),
        ("cellular_data_warning", 2048.0),
        ("net_wifi_ap_channel", "Auto"),  # Channel 0
        ("net_wifi_ap_security", "WPA2"),  # SecurityMode 2
        ("net_wifi_ap_bandwidth", "40 MHz"),  # HtMode 2
        ("net_wan_ip", None),  # "--" placeholder, not an address
        ("net_wan_gateway", None),
        ("net_eth_clients", 2),
        ("net_lan_ip", "192.0.2.170"),
        ("net_lan_netmask", "255.255.248.0"),
        ("net_dhcp_start", "192.0.2.4"),
        ("net_dhcp_end", "192.0.2.254"),
        ("net_dhcp_lease", 172800),
        ("hub_model_number", "E70640"),
        ("hub_bundle_version", "5.30"),
        ("hub_modem_firmware", "TESTMODEM01"),
        ("hub_upgrade_status", "The upgrade program is idle"),
    ],
)
def test_sensor_values(key, expected):
    assert _sensors()[key].value_fn(_merged()) == expected


def test_apn_follows_the_active_sim():
    s = _sensors()["cellular_apn"]
    d = _merged()
    assert s.value_fn(d) == "test.apn"
    # Slot 2 active -> the second profile list.
    d[DATA_MOBILE] = {**MOBILE, "active_sim": 1}
    assert s.value_fn(d) == "other.apn"


def test_wifi_uplink_signal():
    s = _sensors()["net_wifi_uplink_signal"]
    # 0 dBm means "uplink off / no reading" -> suppressed.
    assert s.value_fn(_merged()) is None
    # A real negative RSSI passes through.
    live = {DATA_HOME: {"sta": {"status": 2, "signal": -88, "sta_ssid": "-"}}}
    assert s.value_fn(live) == -88.0


def test_temperature_and_operating_time():
    s = _sensors()
    assert s["hub_temperature"].value_fn(_merged()) == pytest.approx(36.8, abs=0.05)
    assert s["hub_operating_time"].value_fn(_merged()) == pytest.approx(2782.1, abs=0.1)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("cellular_status", True),  # ipv4netstatus 1
        ("net_cloud", True),
        ("net_wifi_ap", True),
        ("net_wifi_uplink", False),  # sta status 0
        ("io_ch5", True),  # types 1
        ("io_ch6", False),
        # --- added for firmware V142.242.530 ---
        ("hub_self_check", False),  # SelfCheck 0 == no problem
        ("hub_upgrading", False),  # status 3 == idle
        ("cellular_ipv6", True),
        ("cellular_data_enabled", True),
        ("cellular_roaming_enabled", True),
        ("net_lan_ipv6", True),
    ],
)
def test_binary_values(key, expected):
    assert _binaries()[key].is_on_fn(_merged()) is expected


def test_self_check_and_upgrade_flag_problems():
    b = _binaries()
    d = _merged()
    d[DATA_SELFCHECK] = {"SelfCheck": 2}
    assert b["hub_self_check"].is_on_fn(d) is True
    d[DATA_UPGRADE] = {"status": 1, "steps": "Downloading"}
    assert b["hub_upgrading"].is_on_fn(d) is True


def test_empty_data_is_safe():
    # Missing sections must yield None/None-ish, never raise.
    for desc in (*SENSORS, *IO_VOLTAGE_SENSORS):
        assert desc.value_fn({}) is None
    for desc in (*BINARY_SENSORS, *IO_SWITCH_SENSORS):
        assert desc.is_on_fn({}) is None
