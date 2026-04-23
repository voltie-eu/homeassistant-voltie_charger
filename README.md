# Voltie Charger for Home Assistant

Home Assistant integration for Voltie EV chargers. Talks to the charger over your LAN using its local HTTP API.

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=flat-square&logo=home-assistant&logoColor=white)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/license-proprietary-red?style=flat-square)](LICENSE)

The dashboard card is a separate repository: [voltie-eu/lovelace-voltie-charger-card](https://github.com/voltie-eu/lovelace-voltie-charger-card).

![Dashboard example](images/dashboard.png)

## Features

- Per-phase voltage, current and power sensors.
- Total charge power, session energy, session duration.
- EVSE state sensor.
- DLM and IPM meter readings.
- Binary sensors for car connected and charging in progress.
- Switches for start/stop, autostart, display, LEDs, buzzer.
- Number entity for the maximum charging current.
- Diagnostics download with credentials redacted.
- mDNS auto-discovery.

## Requirements

- Home Assistant 2025.1 or newer.
- A Voltie Charger with HTTP API enabled. Enable it in the Voltie app under *Settings → Advanced Settings → Experimental → HTTP API config*. Note the username and password if you set them.

## Installation

HACS is the recommended way — it handles updates for you.

### HACS (recommended)

1. **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/voltie-eu/homeassistant-voltie_charger` with category **Integration**.
3. Install **Voltie Charger** and restart Home Assistant.

[![Open your Home Assistant instance and add this repo to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=voltie-eu&repository=homeassistant-voltie_charger&category=integration)

### Manual

1. From the [latest release](https://github.com/voltie-eu/homeassistant-voltie_charger/releases), copy `custom_components/voltie_charger/` into your `config/custom_components/` directory.
2. Restart Home Assistant.

## Setup

After the restart the charger appears under **Settings → Devices & Services** within a minute. Click **Configure** and enter the HTTP API username and password if you set any.

If it doesn't appear (mDNS is often blocked on VLAN-isolated networks), add it manually: **Settings → Devices & Services → Add Integration → Voltie Charger** and enter the charger's IP address.

## Entities

Each charger creates one device with about 40 entities. The main ones:

| Entity | Purpose |
| --- | --- |
| `sensor.<name>_charge_power` | Live charging power (kW). |
| `sensor.<name>_session_energy` | Session energy (kWh). |
| `sensor.<name>_session_charge_time` | Session charge time. |
| `sensor.<name>_evse_state` | EVSE state. |
| `binary_sensor.<name>_car_connected` | Plug detection. |
| `binary_sensor.<name>_charging` | Charging in progress. |
| `switch.<name>_charging` | Start / stop. |
| `number.<name>_current_limit` | Maximum charging current (A). |

Per-phase voltage / current / power and DLM / IPM readings are exposed as individual sensors.

## Troubleshooting

**Authentication fails.** The credentials are the ones set inside the charger's HTTP API config, not your Voltie cloud account.

**Charger not discovered.** Confirm the HTTP API is enabled. Add the charger manually by IP if your network blocks mDNS.

**Entities go `unavailable`.** The integration retries with backoff. If it persists, check the charger is powered and on the network.

## License

Proprietary. Copyright © 2026 Voltie. See [LICENSE](LICENSE).
