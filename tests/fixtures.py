# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Captured YachtSense Link RPC responses, trimmed to what the entities read.

Taken from the real router so the mapping is validated against actual data.
"""

from typing import Any

HOME: dict[str, Any] = {
    "cloud": {"status": "Connected", "cloud_status": 1},
    "sta": {"status": 0, "band": 0, "signal": 0, "sta_ssid": "-"},
    "mobile": {
        "status": 5,
        "signal": 29,
        "provider": "TestCarrier",
        "active_sim": 1,
        "csq": 29,
        "rsrp": -84,
        "rsrq": -10,
        "sinr": 3,
        "act": "FDD LTE",
        "band": "LTE BAND 4",
        "lac": "55F3",
        "cell_id": "C4C7021",
        "ipv4address": "192.0.2.1",
        "ipv4gw": "192.0.2.254",
        "ipv4netstatus": 1,
        "ipv6netstatus": 1,
    },
    "ap": {"status": 1, "name": "TestAP"},
    "wan": {"internet": 3, "ipaddr": "--", "gateway": "--"},
    "dev": {"ap_num": 0, "eth_num": 2},
}

MOBILE: dict[str, Any] = {
    "active_sim": 0,
    "sim": [
        {
            "sim_id": 0,
            "current_data_used": 4270,
            "monthly_data_limit": 3072,
            "left_days": 23,
            "rese_date": "17/08/2026",
            "provider": "TestCarrier",
            "usage_cycle": 17,
            "mobile_data": 1,
            "roam_data": 1,
            "data_warning_flag": 1,
            "data_warning_size": 2048,
            "data": [64, 64, 313, 165, 115, 64, 65, 3202, 218],
            "days": [
                "17/7",
                "18/7",
                "19/7",
                "20/7",
                "21/7",
                "22/7",
                "23/7",
                "24/7",
                "25/7",
            ],
        }
    ],
}

HUB: dict[str, Any] = {
    "Model": "YachtSense Link router",
    "ModelNum": "E70640",
    "TotalVersion": "V142.242.430",
    "PlatformVersion": "cloudconnector.1.4032 n2k.1.7530",
    "BundleVersion": "5.30",
    "ipq_version": "V2.42 2024-04-26 15:34",
    "Module_version": "TESTMODEM01",
    "serial_num": "TESTSERIAL01",
    "IMEI": "000000000000000",
    "Voltage": 13.1,
    "Current_draw": 0.458,
    "Temperature": 309.9,
    "Operating_hours": 10015656,
    "MobileSignalStrength": -55,
}

GPS: dict[str, Any] = {"lat": 40.0, "lng": -70.0}

CONNECTED: dict[str, Any] = {
    "dev_list": [
        {
            "DName": "test-client-1",
            "IPAddress": "192.0.2.20",
            "MACAddress": "02:00:00:00:00:01",
        },
        {
            "DName": "test-client-2",
            "IPAddress": "192.0.2.21",
            "MACAddress": "02:00:00:00:00:02",
        },
    ]
}


def _io_channel(
    n: int, volt: float = 0.0, types: int = 0, status: int = 1
) -> dict[str, Any]:
    return {
        "id": n,
        "name": f"Channel {n}",
        "level": 0,
        "types": types,
        "volt": volt,
        "status": status,
    }


# ch1 reads 12.5 V; ch5 switch is ON; ch4 disabled.
IO: dict[str, Any] = {
    "io_date": [
        _io_channel(1, volt=12.5),
        _io_channel(2),
        _io_channel(3),
        _io_channel(4, status=0),
        _io_channel(5, types=1),
        _io_channel(6),
        _io_channel(7),
        _io_channel(8),
    ]
}


# 0 == every internal module passed its power-on self-check.
SELFCHECK: dict[str, Any] = {"SelfCheck": 0}

UPGRADE: dict[str, Any] = {
    "status": 3,
    "steps": "The upgrade program is idle",
    "count": 0,
    "total": 0,
    "stages": 0,
}

# SecurityMode 2 == WPA2, HtMode 2 == 40 MHz, Channel 0 == auto.
WLAN: dict[str, Any] = {
    "wifi_config": [
        {
            "PhyEnable": 1,
            "HtMode": 2,
            "Channel": 0,
            "vap_config": [{"Ssid": "TestAP", "SecurityMode": 2, "WpaKey": "test-psk"}],
        }
    ]
}

# One profile list per SIM slot, in slot order.
APN: dict[str, Any] = {
    "apns": [
        [
            {
                "id": 0,
                "selected": 1,
                "plmn": 310240,
                "carrier": "TestCarrier",
                "apn": "test.apn",
                "username": "",
                "password": "",
                "ipmode": 0,
            }
        ],
        [
            {
                "id": 0,
                "selected": 1,
                "plmn": 310410,
                "carrier": "OtherCarrier",
                "apn": "other.apn",
                "username": "",
                "password": "",
                "ipmode": 0,
            }
        ],
    ]
}

LAN: dict[str, Any] = {
    "mode": 0,
    "ip_1": "192.0.2.170",
    "ip_2": "192.0.2.12",
    "netmask": "255.255.248.0",
    "gateway": "192.0.2.170",
    "start_ip": "192.0.2.4",
    "end_ip": "192.0.2.254",
    "lease_time": 172800,
    "Eth_IPv6_Enable": 1,
}


def responses() -> dict[str, Any]:
    """method -> result, keyed by the RPC method names the coordinator calls."""
    return {
        "GetHomeStatus": HOME,
        "GetMobile": MOBILE,
        "GetHubInfo": HUB,
        "GetConnectedDevices": CONNECTED,
        "GetGps": GPS,
        "IoConfigure": IO,
        "GetModulesSelfCheckStatus": SELFCHECK,
        "GetUpgradeStatusAndProgress": UPGRADE,
        "GetWlanSettings": WLAN,
        "GetAllApn": APN,
        "LanConfigure": LAN,
    }
