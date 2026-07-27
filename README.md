# YachtSense Link — Home Assistant integration

A local-polling Home Assistant integration for the **Raymarine YachtSense Link**
marine router. It logs in to the router's web interface and reads its JSON-RPC
API to expose cellular signal and data usage, WiFi/WAN status, GPS position,
digital I/O, and device health as native Home Assistant entities.

> Unofficial. Not affiliated with or endorsed by Raymarine.

## Devices & entities

One **YachtSense Link** hub device, with related devices linked to it:

- **Cellular** — connection status, signal %, RSRP/RSRQ/SINR, provider, network
  type, band, IP; data used this cycle, limit, remaining, used %, days left,
  reset date, used today, and a live **throughput** (MB/h).
- **Network** — cloud connection, WiFi access point (+SSID), WiFi uplink
  (+SSID), WiFi clients, connected-device count.
- **GPS** — position (`device_tracker`).
- **I/O** — channels 1–4 input voltage, channels 5–8 switch state.
- **Hub** — input voltage, current draw, temperature, mobile signal, operating
  time, model/firmware/serial/IMEI.

### Data usage over time

The cumulative "Data used (cycle)" sensor is a `total_increasing` sensor, so
Home Assistant's built-in statistics produce **hourly / daily / monthly** usage
automatically (History → Statistics, or a Statistics card). The billing-cycle
reset is handled by HA's statistics.

### A note on throughput

The router exposes only **total** cellular volume (a cumulative counter and
per-day totals) — never a split of upstream vs downstream, and no live per-link
speed API. "Throughput" here is the counter's per-poll delta (total, ~1 MB
granularity). WiFi-uplink data volume is not exposed by the router at all.

## Installation

1. Copy `custom_components/yachtsense_link` to your Home Assistant
   `config/custom_components/` directory (or install via HACS as a custom repo).
2. Restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → _YachtSense Link_.
4. Enter the router's IP address, web-interface username (default `admin`) and
   password, and a poll interval (default 60 s).

## Development

```
uv sync --group dev     # create .venv with test + lint deps
uv run pytest tests/    # run the test suite
```
