# YachtSense Link — Home Assistant integration

A local-polling Home Assistant integration for the **Raymarine YachtSense Link**
marine router. It logs in to the router's web interface and reads its JSON-RPC
API to expose cellular signal and data usage, WiFi/WAN status, GPS position,
digital I/O, and device health as native Home Assistant entities.

> Unofficial. Not affiliated with or endorsed by Raymarine.

## Devices & entities

One **YachtSense Link** hub device, with related devices linked to it:

- **Cellular** — connection status, signal %, RSRP/RSRQ/SINR, provider, network
  type, band, IP, gateway; serving cell ID and location area code; active SIM
  slot, APN, IPv6 status, mobile-data and roaming flags; data used this cycle,
  limit, remaining, used %, days left, reset date and day, warning level, used
  today, and a live **throughput** (MB/h).
- **Network** — cloud connection, WiFi access point (+SSID, channel, security,
  bandwidth), WiFi uplink (+SSID), WiFi clients, Ethernet devices,
  connected-device count, WAN IP/gateway, LAN IP/subnet mask, DHCP pool and
  lease time, LAN IPv6.
- **GPS** — position (`device_tracker`).
- **I/O** — channels 1–4 input voltage, channels 5–8 switch state.
- **Hub** — input voltage, current draw, temperature, mobile signal, operating
  time, model/model number/serial/IMEI, firmware, platform/bundle/router/modem
  versions, module self-check, and upgrade status.

### Data usage over time

The cumulative "Data used (cycle)" sensor is a `total_increasing` sensor, so
Home Assistant's built-in statistics produce **hourly / daily / monthly** usage
automatically (History → Statistics, or a Statistics card). The billing-cycle
reset is handled by HA's statistics.

### Firmware compatibility

Firmware **V142.242.530** moved the router's web API to HTTPS and now redirects
every plain-HTTP request to Raymarine's cloud portal. The integration probes
both schemes and uses whichever the router actually answers on, so it works on
old and new firmware without reconfiguration. TLS is not verified: the router
presents a `CN=yachtsense.raymarine.com` certificate signed by a private
Raymarine CA, which matches neither the LAN address it is reached on nor any
public trust root.

That firmware also moved the GNSS detail page (fix quality, HDOP, satellites in
view, constellation settings) onto a WebSocket on port 7778. It is **not**
usable: the router hands out an auth token but its own WebSocket server rejects
token authentication (`TokenAuthNotAllowed`), so the router's own GNSS page is
broken too. Position still comes from the `GetGps` RPC, which is unaffected.

### A note on throughput

The router exposes only **total** cellular volume (a cumulative counter and
per-day totals) — never a split of upstream vs downstream, and no live per-link
speed API. "Throughput" here is the counter's per-poll delta (total, ~1 MB
granularity). WiFi-uplink data volume is not exposed by the router at all.

## Installation

### HACS (recommended)

This integration is installed by adding it to HACS as a custom repository:

1. In Home Assistant, open **HACS**, then the **⋮** menu (top-right) → **Custom
   repositories**.
2. Add `https://github.com/bakerkj/ha-yachtsense-link` with type
   **Integration**, and click **Add**.
3. Search HACS for **YachtSense Link** and **Download** it.
4. **Restart Home Assistant.**
5. Go to **Settings → Devices & Services → Add Integration → _YachtSense Link_**
   and enter the router's IP address or hostname, web-interface username
   (default `admin`), password, and a poll interval (default 60 s).

### Manual

Alternatively, copy `custom_components/yachtsense_link/` into your Home
Assistant `config/custom_components/` directory, restart Home Assistant, then
add the integration as in step 5 above.

## Development

```
uv sync --group dev     # create .venv with test + lint deps
uv run pytest tests/    # run the test suite
```
