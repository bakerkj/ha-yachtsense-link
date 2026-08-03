# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Sensor platform for the YachtSense Link integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    DATA_APN,
    DATA_HOME,
    DATA_HUB,
    DATA_IO,
    DATA_LAN,
    DATA_MOBILE,
    DATA_THROUGHPUT,
    DATA_UPGRADE,
    DATA_WLAN,
    DEV_CELLULAR,
    DEV_HUB,
    DEV_IO,
    DEV_NETWORK,
    DEV_WIFI_AP,
    DEV_WIFI_UPLINK,
    DOMAIN,
)
from .entity import YsEntity

MB = UnitOfInformation.MEGABYTES


# --- accessors --------------------------------------------------------------


def _home(d: dict[str, Any]) -> dict[str, Any]:
    return d.get(DATA_HOME) or {}


def _mob(d: dict[str, Any]) -> dict[str, Any]:
    return _home(d).get("mobile") or {}


def _sim(d: dict[str, Any]) -> dict[str, Any]:
    m = d.get(DATA_MOBILE) or {}
    sims = m.get("sim") or []
    idx = m.get("active_sim") or 0
    if isinstance(idx, int) and 0 <= idx < len(sims):
        return sims[idx]
    return sims[0] if sims else {}


def _hub(d: dict[str, Any]) -> dict[str, Any]:
    return d.get(DATA_HUB) or {}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ro(v: float | None, nd: int) -> float | None:
    return round(v, nd) if v is not None else None


def _int(v: float | None) -> int | None:
    return int(v) if v is not None else None


def _signal_pct(d: dict[str, Any]) -> StateType:
    csq = _num(_mob(d).get("csq"))
    return round(csq / 31 * 100) if csq is not None and csq <= 31 else None


def _data_remaining(d: dict[str, Any]) -> StateType:
    used, limit = (
        _num(_sim(d).get("current_data_used")),
        _num(_sim(d).get("monthly_data_limit")),
    )
    return round(limit - used, 1) if used is not None and limit is not None else None


def _data_pct(d: dict[str, Any]) -> StateType:
    used, limit = (
        _num(_sim(d).get("current_data_used")),
        _num(_sim(d).get("monthly_data_limit")),
    )
    return (
        round(used / limit * 100, 1)
        if used is not None and limit not in (None, 0)
        else None
    )


def _today(d: dict[str, Any]) -> StateType:
    daily = _sim(d).get("data")
    return _ro(_num(daily[-1]), 1) if isinstance(daily, list) and daily else None


def _temp_c(d: dict[str, Any]) -> StateType:
    k = _num(_hub(d).get("Temperature"))
    return round(k - 273.15, 1) if k is not None else None


def _op_hours(d: dict[str, Any]) -> StateType:
    s = _num(_hub(d).get("Operating_hours"))
    return round(s / 3600.0, 1) if s is not None else None


def _uplink_ssid(d: dict[str, Any]) -> StateType:
    ssid = (_home(d).get("sta") or {}).get("sta_ssid")
    return ssid if ssid and ssid != "-" else None


def _uplink_signal(d: dict[str, Any]) -> StateType:
    # dBm RSSI; 0 means "no reading" (uplink off), so suppress it.
    sig = _num((_home(d).get("sta") or {}).get("signal"))
    return sig if sig is not None and sig < 0 else None


def _client_count(d: dict[str, Any]) -> StateType:
    lst = (d.get("connected") or {}).get("dev_list")
    return len(lst) if isinstance(lst, list) else None


def _lan(d: dict[str, Any]) -> dict[str, Any]:
    return d.get(DATA_LAN) or {}


def _wlan(d: dict[str, Any]) -> dict[str, Any]:
    """The first radio's config from GetWlanSettings."""
    cfgs = (d.get(DATA_WLAN) or {}).get("wifi_config")
    return cfgs[0] if isinstance(cfgs, list) and cfgs else {}


def _vap(d: dict[str, Any]) -> dict[str, Any]:
    """The first virtual AP on the first radio (the boat's own SSID)."""
    vaps = _wlan(d).get("vap_config")
    return vaps[0] if isinstance(vaps, list) and vaps else {}


def _text(v: Any) -> StateType:
    """A router string, with its placeholders ("--", "-", "") treated as absent."""
    return v if isinstance(v, str) and v.strip() not in ("", "-", "--") else None


# GetWlanSettings returns these as small enums; the labels are the ones the
# router's own WiFi page builds its dropdowns from.
_SECURITY_MODES: dict[int, str] = {0: "None", 1: "WPA", 2: "WPA2", 3: "WPA/WPA2"}
_HT_MODES: dict[int, str] = {1: "20 MHz", 2: "40 MHz"}


def _security(d: dict[str, Any]) -> StateType:
    mode = _vap(d).get("SecurityMode")
    return _SECURITY_MODES.get(mode) if isinstance(mode, int) else None


def _bandwidth(d: dict[str, Any]) -> StateType:
    mode = _wlan(d).get("HtMode")
    return _HT_MODES.get(mode) if isinstance(mode, int) else None


def _channel(d: dict[str, Any]) -> StateType:
    ch = _wlan(d).get("Channel")
    # 0 is the router's "pick one for me" setting, not channel zero.
    return "Auto" if ch == 0 else (str(ch) if isinstance(ch, int) else None)


def _apn(d: dict[str, Any]) -> dict[str, Any]:
    """The selected APN profile for the SIM that's currently in use.

    GetAllApn returns one profile list per SIM slot, in slot order.
    """
    slots = (d.get(DATA_APN) or {}).get("apns")
    if not isinstance(slots, list):
        return {}
    m = d.get(DATA_MOBILE) or {}
    idx = m.get("active_sim") if isinstance(m.get("active_sim"), int) else 0
    if not (isinstance(idx, int) and 0 <= idx < len(slots)):
        return {}
    profiles = slots[idx]
    if not isinstance(profiles, list):
        return {}
    for p in profiles:
        if isinstance(p, dict) and p.get("selected") == 1:
            return p
    return profiles[0] if profiles and isinstance(profiles[0], dict) else {}


def _sim_slot(d: dict[str, Any]) -> StateType:
    """The active SIM as a 1-based slot number, matching the router's labelling."""
    idx = (d.get(DATA_MOBILE) or {}).get("active_sim")
    return idx + 1 if isinstance(idx, int) and not isinstance(idx, bool) else None


@dataclass(frozen=True, kw_only=True)
class YsSensorDescription(SensorEntityDescription):
    group: str
    value_fn: Callable[[dict[str, Any]], StateType]


_DATA: dict[str, Any] = {
    "device_class": SensorDeviceClass.DATA_SIZE,
    "native_unit_of_measurement": MB,
}
_DATA_TOTAL: dict[str, Any] = {
    **_DATA,
    "state_class": SensorStateClass.TOTAL_INCREASING,
}

SENSORS: tuple[YsSensorDescription, ...] = (
    # --- cellular ---
    YsSensorDescription(
        key="cellular_signal",
        name="Signal",
        group=DEV_CELLULAR,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:signal",
        value_fn=_signal_pct,
    ),
    YsSensorDescription(
        key="cellular_rsrp",
        name="RSRP",
        group=DEV_CELLULAR,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _num(_mob(d).get("rsrp")),
    ),
    YsSensorDescription(
        key="cellular_rsrq",
        name="RSRQ",
        group=DEV_CELLULAR,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _num(_mob(d).get("rsrq")),
    ),
    YsSensorDescription(
        key="cellular_sinr",
        name="SINR",
        group=DEV_CELLULAR,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _num(_mob(d).get("sinr")),
    ),
    YsSensorDescription(
        key="cellular_provider",
        name="Provider",
        group=DEV_CELLULAR,
        icon="mdi:sim",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _mob(d).get("provider") or None,
    ),
    YsSensorDescription(
        key="cellular_network_type",
        name="Network type",
        group=DEV_CELLULAR,
        icon="mdi:radio-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _mob(d).get("act") or None,
    ),
    YsSensorDescription(
        key="cellular_band",
        name="Band",
        group=DEV_CELLULAR,
        icon="mdi:radio-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _mob(d).get("band") or None,
    ),
    YsSensorDescription(
        key="cellular_ip",
        name="IP address",
        group=DEV_CELLULAR,
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _mob(d).get("ipv4address") or None,
    ),
    YsSensorDescription(
        key="cellular_data_used",
        name="Data used (cycle)",
        group=DEV_CELLULAR,
        icon="mdi:database",
        value_fn=lambda d: _ro(_num(_sim(d).get("current_data_used")), 1),
        **_DATA_TOTAL,
    ),
    YsSensorDescription(
        key="cellular_data_limit",
        name="Data limit",
        group=DEV_CELLULAR,
        icon="mdi:database-arrow-up",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _num(_sim(d).get("monthly_data_limit")),
        **_DATA,
    ),
    YsSensorDescription(
        key="cellular_data_remaining",
        name="Data remaining",
        group=DEV_CELLULAR,
        icon="mdi:database-minus",
        value_fn=_data_remaining,
        **_DATA,
    ),
    YsSensorDescription(
        key="cellular_data_used_pct",
        name="Data used %",
        group=DEV_CELLULAR,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=_data_pct,
    ),
    YsSensorDescription(
        key="cellular_days_left",
        name="Days left in cycle",
        group=DEV_CELLULAR,
        native_unit_of_measurement="d",
        icon="mdi:calendar-clock",
        value_fn=lambda d: _int(_num(_sim(d).get("left_days"))),
    ),
    YsSensorDescription(
        key="cellular_reset_date",
        name="Cycle reset date",
        group=DEV_CELLULAR,
        icon="mdi:calendar-refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _sim(d).get("rese_date") or None,
    ),
    YsSensorDescription(
        key="cellular_data_today",
        name="Data used today",
        group=DEV_CELLULAR,
        icon="mdi:database-clock",
        value_fn=_today,
        **_DATA_TOTAL,
    ),
    YsSensorDescription(
        key="cellular_throughput",
        name="Throughput",
        group=DEV_CELLULAR,
        native_unit_of_measurement="MB/h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        value_fn=lambda d: (d.get(DATA_THROUGHPUT) or {}).get("rate_mb_per_h"),
    ),
    # --- hub health ---
    YsSensorDescription(
        key="hub_voltage",
        name="Input voltage",
        group=DEV_HUB,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _ro(_num(_hub(d).get("Voltage")), 2),
    ),
    YsSensorDescription(
        key="hub_current",
        name="Current draw",
        group=DEV_HUB,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _ro(_num(_hub(d).get("Current_draw")), 3),
    ),
    YsSensorDescription(
        key="hub_temperature",
        name="Temperature",
        group=DEV_HUB,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_temp_c,
    ),
    YsSensorDescription(
        key="hub_signal",
        name="Mobile signal",
        group=DEV_HUB,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _num(_hub(d).get("MobileSignalStrength")),
    ),
    YsSensorDescription(
        key="hub_operating_time",
        name="Operating time",
        group=DEV_HUB,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
        value_fn=_op_hours,
    ),
    YsSensorDescription(
        key="hub_model",
        name="Model",
        group=DEV_HUB,
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _hub(d).get("Model") or None,
    ),
    YsSensorDescription(
        key="hub_firmware",
        name="Firmware",
        group=DEV_HUB,
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _hub(d).get("TotalVersion") or None,
    ),
    YsSensorDescription(
        key="hub_serial",
        name="Serial number",
        group=DEV_HUB,
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _hub(d).get("serial_num") or None,
    ),
    YsSensorDescription(
        key="hub_imei",
        name="IMEI",
        group=DEV_HUB,
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _hub(d).get("IMEI") or None,
    ),
    # --- network ---
    YsSensorDescription(
        key="net_wifi_ap_ssid",
        name="SSID",
        group=DEV_WIFI_AP,
        icon="mdi:wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (_home(d).get("ap") or {}).get("name") or None,
    ),
    YsSensorDescription(
        key="net_wifi_uplink_ssid",
        name="SSID",
        group=DEV_WIFI_UPLINK,
        icon="mdi:wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_uplink_ssid,
    ),
    YsSensorDescription(
        key="net_wifi_uplink_signal",
        name="Signal",
        group=DEV_WIFI_UPLINK,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_uplink_signal,
    ),
    YsSensorDescription(
        key="net_wifi_clients",
        name="Clients",
        group=DEV_WIFI_AP,
        icon="mdi:devices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _int(_num((_home(d).get("dev") or {}).get("ap_num"))),
    ),
    YsSensorDescription(
        key="net_clients",
        name="Connected devices",
        group=DEV_NETWORK,
        icon="mdi:lan-connect",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_client_count,
    ),
    # --- cellular: serving cell and SIM detail ---
    YsSensorDescription(
        key="cellular_sim_slot",
        name="Active SIM",
        group=DEV_CELLULAR,
        icon="mdi:sim",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sim_slot,
    ),
    YsSensorDescription(
        key="cellular_apn",
        name="APN",
        group=DEV_CELLULAR,
        icon="mdi:transit-connection-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_apn(d).get("apn")),
    ),
    YsSensorDescription(
        key="cellular_cell_id",
        name="Cell ID",
        group=DEV_CELLULAR,
        icon="mdi:radio-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_mob(d).get("cell_id")),
    ),
    YsSensorDescription(
        key="cellular_lac",
        name="Location area code",
        group=DEV_CELLULAR,
        icon="mdi:map-marker-radius",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_mob(d).get("lac")),
    ),
    YsSensorDescription(
        key="cellular_gateway",
        name="Gateway",
        group=DEV_CELLULAR,
        icon="mdi:ip-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_mob(d).get("ipv4gw")),
    ),
    YsSensorDescription(
        key="cellular_cycle_reset_day",
        name="Cycle reset day",
        group=DEV_CELLULAR,
        icon="mdi:calendar-start",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(_num(_sim(d).get("usage_cycle"))),
    ),
    YsSensorDescription(
        key="cellular_data_warning",
        name="Data warning level",
        group=DEV_CELLULAR,
        icon="mdi:database-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            _num(_sim(d).get("data_warning_size"))
            if _sim(d).get("data_warning_flag") == 1
            else None
        ),
        **_DATA,
    ),
    # --- WiFi access point config ---
    YsSensorDescription(
        key="net_wifi_ap_channel",
        name="Channel",
        group=DEV_WIFI_AP,
        icon="mdi:wifi-settings",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_channel,
    ),
    YsSensorDescription(
        key="net_wifi_ap_security",
        name="Security",
        group=DEV_WIFI_AP,
        icon="mdi:wifi-lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_security,
    ),
    YsSensorDescription(
        key="net_wifi_ap_bandwidth",
        name="Bandwidth",
        group=DEV_WIFI_AP,
        icon="mdi:arrow-expand-horizontal",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_bandwidth,
    ),
    # --- WAN / LAN ---
    YsSensorDescription(
        key="net_wan_ip",
        name="WAN IP address",
        group=DEV_NETWORK,
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text((_home(d).get("wan") or {}).get("ipaddr")),
    ),
    YsSensorDescription(
        key="net_wan_gateway",
        name="WAN gateway",
        group=DEV_NETWORK,
        icon="mdi:ip-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text((_home(d).get("wan") or {}).get("gateway")),
    ),
    YsSensorDescription(
        key="net_eth_clients",
        name="Ethernet devices",
        group=DEV_NETWORK,
        icon="mdi:ethernet",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _int(_num((_home(d).get("dev") or {}).get("eth_num"))),
    ),
    YsSensorDescription(
        key="net_lan_ip",
        name="LAN IP address",
        group=DEV_NETWORK,
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_lan(d).get("ip_1")),
    ),
    YsSensorDescription(
        key="net_lan_netmask",
        name="LAN subnet mask",
        group=DEV_NETWORK,
        icon="mdi:ip-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_lan(d).get("netmask")),
    ),
    YsSensorDescription(
        key="net_dhcp_start",
        name="DHCP pool start",
        group=DEV_NETWORK,
        icon="mdi:ip-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_lan(d).get("start_ip")),
    ),
    YsSensorDescription(
        key="net_dhcp_end",
        name="DHCP pool end",
        group=DEV_NETWORK,
        icon="mdi:ip-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_lan(d).get("end_ip")),
    ),
    YsSensorDescription(
        key="net_dhcp_lease",
        name="DHCP lease time",
        group=DEV_NETWORK,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _int(_num(_lan(d).get("lease_time"))),
    ),
    # --- hub: firmware detail and upgrade state ---
    YsSensorDescription(
        key="hub_model_number",
        name="Model number",
        group=DEV_HUB,
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_hub(d).get("ModelNum")),
    ),
    YsSensorDescription(
        key="hub_platform_version",
        name="Platform version",
        group=DEV_HUB,
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_hub(d).get("PlatformVersion")),
    ),
    YsSensorDescription(
        key="hub_bundle_version",
        name="Bundle version",
        group=DEV_HUB,
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_hub(d).get("BundleVersion")),
    ),
    YsSensorDescription(
        key="hub_router_version",
        name="Router firmware",
        group=DEV_HUB,
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_hub(d).get("ipq_version")),
    ),
    YsSensorDescription(
        key="hub_modem_firmware",
        name="Modem firmware",
        group=DEV_HUB,
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text(_hub(d).get("Module_version")),
    ),
    YsSensorDescription(
        key="hub_upgrade_status",
        name="Upgrade status",
        group=DEV_HUB,
        icon="mdi:package-down",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _text((d.get(DATA_UPGRADE) or {}).get("steps")),
    ),
)


def _io_voltage_fn(idx: int) -> Callable[[dict[str, Any]], StateType]:
    def fn(d: dict[str, Any]) -> StateType:
        chans = (
            (d.get(DATA_IO) or {}).get("io_date")
            or (d.get(DATA_IO) or {}).get("io_data")
            or []
        )
        if idx >= len(chans) or not isinstance(chans[idx], dict):
            return None
        ch = chans[idx]
        volt = _num(ch.get("volt"))
        if ch.get("status") == 1 and volt is not None and volt >= 0:
            return round(volt, 2)
        return None

    return fn


# I/O channels 1-4 are voltage-monitoring inputs.
IO_VOLTAGE_SENSORS: tuple[YsSensorDescription, ...] = tuple(
    YsSensorDescription(
        key=f"io_ch{n}_voltage",
        name=f"Channel {n} voltage",
        group=DEV_IO,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sine-wave",
        value_fn=_io_voltage_fn(n - 1),
    )
    for n in range(1, 5)
)


class YsSensor(YsEntity, SensorEntity):
    """A YachtSense Link sensor."""

    entity_description: YsSensorDescription

    def __init__(self, coordinator: Any, description: YsSensorDescription) -> None:
        super().__init__(coordinator, description.group, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up YachtSense Link sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        YsSensor(coordinator, desc) for desc in (*SENSORS, *IO_VOLTAGE_SENSORS)
    )
