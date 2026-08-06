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
    GNSS_MAX_FIX_AGE,
    GNSS_NO_FIX,
)
from custom_components.yachtsense_link.device_tracker import _position
from custom_components.yachtsense_link.sensor import IO_VOLTAGE_SENSORS, SENSORS

from .fixtures import (
    APN,
    CONNECTED,
    GNSS,
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
        DATA_IO: IO,
        DATA_SELFCHECK: SELFCHECK,
        DATA_UPGRADE: UPGRADE,
        DATA_WLAN: WLAN,
        DATA_APN: APN,
        DATA_LAN: LAN,
        DATA_THROUGHPUT: {"rate_mb_per_h": 123.4},
        DATA_GNSS: {**GNSS, "fix_age": 4.0},
    }


def _sensors() -> dict:
    return {d.key: d for d in (*SENSORS, *IO_VOLTAGE_SENSORS)}


def _binaries() -> dict:
    return {d.key: d for d in (*BINARY_SENSORS, *IO_SWITCH_SENSORS)}


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("cellular_signal_quality", 94),  # csq 29/31 -> 94%
        ("cellular_rsrp", -84.0),
        ("cellular_provider", "TestCarrier"),
        ("cellular_band", "LTE BAND 4"),
        ("cellular_data_used_cycle", 4270.0),
        ("cellular_plan_limit", 3072.0),
        ("cellular_data_remaining", -1198.0),  # over the plan cap
        ("cellular_plan_used_cycle", 139.0),
        ("cellular_days_left", 23),
        ("cellular_data_today", 218.0),
        ("cellular_throughput", 123.4),
        ("hub_voltage", 13.1),
        ("hub_current", 0.458),
        ("cellular_signal_strength", -55.0),
        ("hub_model", "YachtSense Link router"),
        ("hub_serial", "TESTSERIAL01"),
        ("wifi_ap_ssid", "TestAP"),
        ("wifi_uplink_ssid", None),  # sta_ssid is "-"
        ("wifi_ap_clients", 0),
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
        ("wifi_ap_channel", "Auto"),  # Channel 0
        ("wifi_ap_security", "WPA2"),  # SecurityMode 2
        ("wifi_ap_bandwidth", "40 MHz"),  # HtMode 2
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
    s = _sensors()["wifi_uplink_signal"]
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
        ("wifi_ap_status", True),
        ("wifi_uplink_status", False),  # sta status 0
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


# --- GNSS -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("gnss_fix_type", "Differential fix"),
        ("gnss_satellites_used", 2),  # two of three flagged isUsedInFix
        ("gnss_satellites_visible", 3),
        ("gnss_fix_age", 4.0),
    ],
)
def test_gnss_sensor_values(key, expected):
    assert _sensors()[key].value_fn(_merged()) == expected


def test_gnss_hdop_value():
    assert _sensors()["gnss_hdop"].value_fn(_merged()) == pytest.approx(0.48, abs=1e-3)


def test_gnss_sensors_are_none_without_a_report():
    data = {**_merged(), DATA_GNSS: None}
    for key in ("gnss_fix_type", "gnss_satellites_used", "gnss_hdop", "gnss_fix_age"):
        assert _sensors()[key].value_fn(data) is None


# --- position ---------------------------------------------------------------


def test_position_prefers_the_gnss_report():
    lat, lng = _position(_merged())
    assert (lat, lng) == pytest.approx((43.058032989, -70.726982116), abs=1e-6)


def test_position_is_none_without_a_gnss_report():
    data = {**_merged()}
    del data[DATA_GNSS]
    assert _position(data) == (None, None)


def test_position_is_none_when_the_fix_is_stale():
    stale = {**_merged(), DATA_GNSS: {**GNSS, "fix_age": GNSS_MAX_FIX_AGE + 1}}
    assert _position(stale) == (None, None)


def test_position_is_none_while_the_endpoint_is_down():
    # There is no second source to fall back to, by design: reporting nothing
    # beats reporting a position that may be hours old.
    assert _position({**_merged(), DATA_GNSS: None}) == (None, None)


@pytest.mark.parametrize("fix", sorted(GNSS_NO_FIX))
def test_position_is_none_without_a_fix(fix):
    # Every no-fix value must suppress the position, not just "0": the payload
    # still carries a stale Latitude/Longitude when the receiver has no
    # solution, so a missed value here reports a position that does not exist.
    nofix = {
        **_merged(),
        DATA_GNSS: {**GNSS, "gnss": {**GNSS["gnss"], "Fix": fix}, "fix_age": 1.0},
    }
    assert _position(nofix) == (None, None)


@pytest.mark.parametrize("fix", sorted(GNSS_NO_FIX))
def test_fix_type_and_position_agree_on_no_fix(fix):
    # The sensor and the tracker must never disagree about whether a fix
    # exists; both read GNSS_NO_FIX so they cannot drift apart.
    data = {
        **_merged(),
        DATA_GNSS: {**GNSS, "gnss": {**GNSS["gnss"], "Fix": fix}, "fix_age": 1.0},
    }
    assert _sensors()["gnss_fix_type"].value_fn(data) == "No fix"
    assert _position(data) == (None, None)


@pytest.mark.parametrize(("fix", "label"), [("1", "Fix"), ("2", "Differential fix")])
def test_fix_type_and_position_agree_on_a_real_fix(fix, label):
    # Fix 1 is an ordinary fix and 2 a differential one -- both are usable
    # positions. Only 0 means the receiver has no solution.
    data = {
        **_merged(),
        DATA_GNSS: {**GNSS, "gnss": {**GNSS["gnss"], "Fix": fix}, "fix_age": 1.0},
    }
    assert _sensors()["gnss_fix_type"].value_fn(data) == label
    assert _position(data) != (None, None)


def test_position_rejects_the_null_island_sentinel():
    zeroed = {
        **_merged(),
        DATA_GNSS: {
            **GNSS,
            "gnss": {**GNSS["gnss"], "Latitude": "0.0", "Longitude": "0.0"},
            "fix_age": 1.0,
        },
    }
    assert _position(zeroed) == (None, None)


def test_position_accepts_a_fix_just_inside_the_age_limit():
    fresh = {**_merged(), DATA_GNSS: {**GNSS, "fix_age": GNSS_MAX_FIX_AGE - 1}}
    assert _position(fresh) != (None, None)


def test_observation_lag_never_blanks_the_position():
    # Measured in production at over four hours while the receiver held a good
    # fix and reads were succeeding: it does not track staleness and must not
    # retire a position.
    data = {
        **_merged(),
        DATA_GNSS: {
            **GNSS,
            "fix_age": 1.0,
            "report_age": 1.0,
            "observation_lag": 14893.6,
        },
    }
    assert _position(data) != (None, None)


@pytest.mark.parametrize("key", ["fix_age", "report_age"])
def test_the_clock_based_ages_do_blank_the_position(key):
    data = {
        **_merged(),
        DATA_GNSS: {
            **GNSS,
            "fix_age": 1.0,
            "report_age": 1.0,
            key: GNSS_MAX_FIX_AGE + 1,
        },
    }
    assert _position(data) == (None, None)


def test_unknown_liveness_still_reports_a_position():
    # fix_age None means the report carried no observation counter, so
    # staleness is unknown -- that must not be treated as stale.
    data = {**_merged(), DATA_GNSS: {**GNSS, "fix_age": None}}
    assert _position(data) != (None, None)
