# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Constants for the YachtSense Link integration."""

from typing import Final

DOMAIN: Final = "yachtsense_link"

# Config entry keys
CONF_HOST: Final = "host"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_UPDATE_INTERVAL: Final = "update_interval"

DEFAULT_USERNAME: Final = "admin"
DEFAULT_UPDATE_INTERVAL: Final = 60
MIN_UPDATE_INTERVAL: Final = 15

# JSON-RPC methods polled each cycle. GetGps is called "GetGps" but the router
# echoes it back as "GetGpsData"; IoConfigure needs mode 0 to read.
METHOD_HOME: Final = "GetHomeStatus"
METHOD_MOBILE: Final = "GetMobile"
METHOD_HUB: Final = "GetHubInfo"
METHOD_CONNECTED: Final = "GetConnectedDevices"
METHOD_GPS: Final = "GetGps"
METHOD_IO: Final = "IoConfigure"
IO_READ_PARAMS: Final = {"mode": "0"}

# Merged-data keys used by the coordinator and entities.
DATA_HOME: Final = "home"
DATA_MOBILE: Final = "mobile"
DATA_HUB: Final = "hub"
DATA_CONNECTED: Final = "connected"
DATA_GPS: Final = "gps"
DATA_IO: Final = "io"
DATA_THROUGHPUT: Final = "throughput"

# Device group identifiers (one HA device each, all via_device the hub).
DEV_HUB: Final = "hub"
DEV_CELLULAR: Final = "cellular"
DEV_NETWORK: Final = "network"
DEV_WIFI_AP: Final = "wifi_ap"
DEV_WIFI_UPLINK: Final = "wifi_uplink"
DEV_GPS: Final = "gps"
DEV_IO: Final = "io"

# Cellular data volumes are reported in MB (a 3072 == 3 GB plan).
DATA_UNIT_MB: Final = "MB"
