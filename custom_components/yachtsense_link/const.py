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

# JSON-RPC methods polled each cycle. IoConfigure needs mode 0 to read.
# Position is not among them; it comes from the GNSS endpoint (see GNSS_PORT).
METHOD_HOME: Final = "GetHomeStatus"
METHOD_MOBILE: Final = "GetMobile"
METHOD_HUB: Final = "GetHubInfo"
METHOD_CONNECTED: Final = "GetConnectedDevices"
METHOD_IO: Final = "IoConfigure"
METHOD_SELFCHECK: Final = "GetModulesSelfCheckStatus"
METHOD_UPGRADE: Final = "GetUpgradeStatusAndProgress"
IO_READ_PARAMS: Final = {"mode": "0"}

# Rarely-changing configuration, polled on a slower cadence (see SLOW_EVERY).
METHOD_WLAN: Final = "GetWlanSettings"
METHOD_APN: Final = "GetAllApn"
METHOD_LAN: Final = "LanConfigure"
# LanConfigure is a write verb for every mode except 3, which is the read the
# router's own LAN page uses. Do NOT poll any other mode: mode 0 applies the
# DHCP-server form, mode 8 applies the IPv6 form.
LAN_READ_PARAMS: Final = {"mode": 3}

# How many poll cycles between refreshes of the slow/config methods above.
SLOW_EVERY: Final = 15

# The router answers unauthenticated HTTP on this port with a detailed GNSS
# report: fix type, DOP values, per-satellite detail and a timestamp that tracks
# the fix rather than the request. The timestamp is the point -- it is what lets
# a fix that has stopped updating be told apart from a current one.
GNSS_PORT: Final = 9999
GNSS_PATH: Final = "/getGnss"
# When it has no data to hand back the endpoint answers 503 after about five
# seconds; allow a little past that so the failure is read rather than cut
# short, while two attempts still fit inside MIN_UPDATE_INTERVAL.
GNSS_TIMEOUT: Final = 6.0
# Retry delay measured from the *start* of the first attempt, so a slow 503
# (which already consumed most of it) is retried promptly while a fast failure
# such as connection-refused waits out the remainder instead of hammering.
GNSS_RETRY_DELAY: Final = 5.0
# A fix whose reported timestamp has not advanced for this long is treated as
# stale rather than as a live position. Deliberately tight: reporting no
# position costs little, whereas presenting a frozen one as live is the failure
# this endpoint exists to avoid. Set above the endpoint's normal pauses between
# fix updates but below the default poll interval doubled, so an ordinary pause
# cannot span two polls and trip it.
GNSS_MAX_FIX_AGE: Final = 90.0
# "Fix" values meaning the receiver has no solution. This is NOT the GSA
# convention: on this router 0 is no fix, 1 is an ordinary fix and 2 is a
# differential fix, so anything above zero is a usable position. Shared so the
# position check and the fix-type sensor cannot disagree about whether a fix
# exists.
GNSS_NO_FIX: Final = frozenset({"0"})
GNSS_FIX_LABELS: Final = {"0": "No fix", "1": "Fix", "2": "Differential fix"}

# Merged-data keys used by the coordinator and entities.
DATA_HOME: Final = "home"
DATA_MOBILE: Final = "mobile"
DATA_HUB: Final = "hub"
DATA_CONNECTED: Final = "connected"
DATA_IO: Final = "io"
DATA_THROUGHPUT: Final = "throughput"
DATA_SELFCHECK: Final = "selfcheck"
DATA_UPGRADE: Final = "upgrade"
DATA_WLAN: Final = "wlan"
DATA_APN: Final = "apn"
DATA_LAN: Final = "lan"
DATA_GNSS: Final = "gnss"

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
