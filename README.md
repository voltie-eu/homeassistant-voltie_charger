# Voltie Charger for Home Assistant

Home Assistant integration for Voltie chargers. Talks to the charger over your LAN using its local HTTP API.

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=flat-square&logo=home-assistant&logoColor=white)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/license-proprietary-red?style=flat-square)](LICENSE)

The dashboard card is a separate repository: [voltie-eu/lovelace-voltie-charger-card](https://github.com/voltie-eu/lovelace-voltie-charger-card).

Built against **HTTP API v5.0**. Features the charger's firmware doesn't provide are hidden or reported unavailable rather than failing, so older firmware keeps working.

## Features

- Per-phase voltage, current and power sensors.
- Total charge power, session energy, session duration.
- EVSE state sensor.
- DLM and IPM meter readings.
- Binary sensors for car connected and charging in progress.
- Switches for start/stop, autostart, display, LEDs, buzzer, out of service and forced single-phase charging.
- Number entities for the charging current limit and the load-management and grid-control parameters.
- Selects for the load-management mode and access mode.
- Buttons to reboot the charger and to run RFID learn mode.
- Services for the display, the rear LED and RFID tag management.
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

Each charger creates one device with about 60 entities. The main ones:

| Entity | Purpose |
| --- | --- |
| `sensor.<name>_charge_power` | Live charging power (kW). |
| `sensor.<name>_session_energy` | Session energy (kWh). |
| `sensor.<name>_session_charge_time` | Session charge time. |
| `sensor.<name>_evse_state` | EVSE state. |
| `sensor.<name>_active_phases` | Phases used by the current session. |
| `sensor.<name>_phases_wired` | Phases wired into the charger. |
| `sensor.<name>_hardware_current_limit` | Highest current the hardware supports (A). |
| `binary_sensor.<name>_car_connected` | Plug detection. |
| `binary_sensor.<name>_charging` | Charging in progress. |
| `switch.<name>_charging_enabled` | Start / stop. |
| `switch.<name>_out_of_service` | Take the charger out of service. |
| `switch.<name>_force_single_phase_charging` | Force single-phase charging. |
| `number.<name>_maximum_charging_current` | Charging current limit (A). |
| `select.<name>_load_management_mode` | Off / dynamic / eco / green / grid control. |
| `select.<name>_access_mode` | Home charger, with or without RFID. |
| `button.<name>_reboot_charger` | Reboot the charger. |

Per-phase voltage / current / power, DLM / IPM readings, the grid-control parameters and the RFID reader status are exposed as individual entities. Some diagnostic entities are disabled by default — enable them from the device page.

`number.<name>_maximum_charging_current` takes its upper bound from the charger's own `current_hw_limit`, capped at the 32 A the API accepts.

## Actions

| Action | Purpose |
| --- | --- |
| `voltie_charger.display_text` | Scroll a message across the charger's display. |
| `voltie_charger.set_rear_led` | Set the rear LED colour and brightness for a period. |
| `voltie_charger.start_charging` | Start a session, optionally recording an RFID tag. |
| `voltie_charger.add_rfid_tag` | Add a tag to the charger's stored list. |
| `voltie_charger.modify_rfid_tag` | Change a stored tag's name, comment or enabled flag. |
| `voltie_charger.delete_rfid_tag` | Remove a stored tag. |
| `voltie_charger.list_rfid_tags` | Return the stored tags as action response data. |
| `voltie_charger.start_rfid_learn` | Start learn mode with a timeout and tag count. |

Each action targets one charger device. The RFID actions require API v5 firmware.

**RFID tag IDs must be hexadecimal** (0-9, A-F), 8 to 20 characters. The API documentation describes a wider character set, but the firmware rejects anything else, so these actions validate it up front rather than letting the charger return a generic error.

## Upgrading from v0.2.x

Existing entities keep their entity IDs, so dashboards and automations continue to work. Two cosmetic details are worth knowing:

- The `phases` sensor was renamed to **Phases wired**, because the API clarified that the field means phases wired into the charger rather than phases in use. On an upgraded install it keeps its original `..._phases_in_use` entity ID, so that ID no longer matches its name. The new session-phase sensor is **Active phases**.
- New entities may pick up an area prefix in their entity ID (for example `sensor.garage_voltie_charger_1234_active_phases`) while pre-existing ones do not, because Home Assistant derives IDs from the device's area at creation time. Removing and re-adding the integration gives a consistent set, at the cost of losing entity history.

## Firmware compatibility

The integration adapts to what the charger reports:

- Configuration entities whose `/config` key is missing read as unavailable.
- RFID entities are only created when the charger answers `GET /rfid/status`. After a firmware upgrade, reload the integration to pick them up.
- `/extras` commands that the firmware rejects as unknown produce an error telling you to update the charger.

`sensor.<name>_api_version` reports the charger's major API version, which is useful in support tickets.

## Troubleshooting 🛠️

**Authentication fails.** The credentials are the ones set inside the charger's HTTP API config, not your Voltie cloud account.

**Charger not discovered.** Confirm the HTTP API is enabled. Add the charger manually by IP if your network blocks mDNS.

**Entities go `unavailable`.** The integration retries with backoff. If it persists, check the charger is powered and on the network.

**RFID entities are missing.** They need API v5 firmware. Check `sensor.<name>_api_version`, then reload the integration after updating the charger.

**"Not master" errors on RFID actions.** The charger is a secondary unit in a prepaid-RFID cluster — send the action to the master unit instead.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

## License

Proprietary. Copyright © 2026 Voltie. See [LICENSE](LICENSE).
