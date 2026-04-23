# Voltie Charger for Home Assistant

Home Assistant integration for Voltie chargers. Talks to the charger over your LAN using its local HTTP API.

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=flat-square&logo=home-assistant&logoColor=white)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/license-proprietary-red?style=flat-square)](LICENSE)

The dashboard card is a separate repository: [voltie-eu/lovelace-voltie-charger-card](https://github.com/voltie-eu/lovelace-voltie-charger-card).

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
- [HACS](https://www.hacs.xyz/docs/use/download/download/) installed.
- A Voltie Charger on your LAN with HTTP API enabled in the Voltie mobile app. If you set a username and password, you'll need them during setup.

## Installation 📦

HACS is the recommended way — it handles updates for you.

1. Open **HACS** in the sidebar.
2. Open the **⋮** menu → **Custom repositories**.
3. Fill in the dialog:
   - **Repository:** `https://github.com/voltie-eu/homeassistant-voltie_charger`
   - **Type:** **Integration**
4. Click **Add**.
5. Back on the HACS main page, search for `Voltie Charger`.
6. Click the result and click **Download**.
7. Confirm the latest version and click **Download** again.
8. Restart Home Assistant.

## Setup 🔌

After the restart, the charger is usually found automatically via mDNS within a minute.

1. Go to **Settings → Devices & services**.
2. A **Voltie Charger** appears under **Discovered** with the charger's ID.
3. Click **Add**.
4. If the charger has credentials set, enter the **Username** and **Password**. Otherwise the form submits directly.
5. Click **Submit**, then **Finish**.

If it doesn't appear (mDNS is often blocked on VLAN-isolated networks), add it manually: **Settings → Devices & services → Add integration → Voltie Charger**, then enter the charger's IP address and credentials.

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

## Troubleshooting 🛠️

**Authentication fails.** The credentials are the ones set inside the charger's HTTP API config, not your Voltie cloud account.

**Charger not discovered.** Confirm the HTTP API is enabled. Add the charger manually by IP if your network blocks mDNS.

**Entities go `unavailable`.** The integration retries with backoff. If it persists, check the charger is powered and on the network.

## License

Proprietary. Copyright © 2026 Voltie. See [LICENSE](LICENSE).
