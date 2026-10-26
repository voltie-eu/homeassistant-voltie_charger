# Voltie Charger for Home Assistant

Home Assistant integration for Voltie chargers. Talks to the charger over your LAN using its local HTTP API.

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=flat-square&logo=home-assistant&logoColor=white)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square)](LICENSE)

The dashboard card is a separate repository: [voltie-eu/lovelace-voltie-charger-card](https://github.com/voltie-eu/lovelace-voltie-charger-card).

Built against **HTTP API v5.0**. Features the charger's firmware doesn't provide are hidden or reported unavailable rather than failing, so older firmware keeps working.

v0.5.0 is the last release of this custom integration. The Voltie Charger integration is moving into Home Assistant itself.

## Moving to the built-in integration

Your entities, entity IDs, history and settings come with you. Do it in this order:

1. **Update the [Voltie Charger Card](https://github.com/voltie-eu/lovelace-voltie-charger-card) to v0.5.0 first.**
   Older cards cannot find the entities after step 2.
2. **Install v0.5.0 of this integration and restart Home Assistant once.**
   This re-keys the entities to the format of the built-in integration.
   Entity IDs, history, names and other settings stay.
3. **When the built-in Voltie Charger integration is in your Home Assistant version:**
   remove this custom integration from HACS (Marketplace) and restart.
   Do not delete the Voltie Charger entry under **Settings → Devices & services**.
   The built-in integration takes over the same config entry, device and entities.

Skipping step 2 leaves you with a second set of entities, with new entity IDs.

### Actions that change

The built-in integration changes some action fields.
Edit the automations and scripts that use these actions after the move:

| Action | Here | Built-in |
| --- | --- | --- |
| all actions | the charger is the action's **target** | the charger is the **Charger** field, `device_id` |
| `set_rear_led` | `color_rgb`, hex text like `#FF8800` | `rgb_color`, a color picker, `[255, 136, 0]` in YAML |
| `set_rear_led` | `brightness`, 0.0 to 1.0 | `brightness`, 0 to 100 percent |
| `set_rear_led` | `duration_sec` | `duration` |
| `add_rfid_tag`, `modify_rfid_tag`, `delete_rfid_tag` | `id` | `tag_id` |
| `start_rfid_learn` | `timeout_sec` | `duration` |

`list_rfid_tags` answers in a new shape.
Each tag has `tag_id` and `last_used` (a date) instead of `id` and `last_use`.
`total` replaces `count`, and `list_hash` is gone.

## Changes in 0.5.0

1. **Update the card to v0.5.0 first.** Older cards show the charger as offline.
2. **Required before moving to the built-in integration.** See above.
3. What changed, to match the built-in integration:
   - Entity unique IDs use the built-in format, `<charger_id>_<key>`.
     Entity IDs, history and settings stay.
   - Removed sensors: API version, RFID list hash, RFID list format version.
     The API version is in the diagnostics download.
   - Removed repair notices: outdated firmware, HTTP API without a password.
   - Removed the polling interval option. The charger is polled every 30 seconds.
   - Removed attributes: `raw_code` of the EVSE state,
     `session_start` and `periods` of session energy,
     `error` and `raw_code` of the problem sensor.
   - EVSE state is a main entity now, no longer diagnostic.
     It reads unknown where it read `unknown` or `error`.
   - EVSE state 22 is `sleeping` instead of `waiting_for_timer`.
     The firmware no longer uses this state.
   - Mains voltage and phases wired are diagnostic entities.
   - Per-phase voltage, current and power are diagnostic.
     New installs get them disabled; existing ones stay enabled.
   - Problem and Charging take their names from Home Assistant.
     In Hungarian they read Probléma and Töltődik.
   - The RFID learn buttons are configuration entities.
   - Icons and display precision follow the built-in integration.
   - Entries titled "Voltie Charger (address)" become "Voltie Charger 1234",
     the device's name. The built-in integration names the device after it.
   - Every entry stores its port, as the built-in integration needs it.
   - The actions no longer use a call Home Assistant 2026.10 deprecated.
4. Fixes:
   - Adding a charger by hand works while its discovery is offered.
     It failed with "already in progress".
   - The discovery card of a charger with a password or with its HTTP API
     off goes away once the charger is added by hand.

Do not go back to v0.4.0 after this release: it would add a second set of entities. To downgrade anyway, remove the integration first.

## Features

- Total charge power, session energy, session duration, and a lifetime energy meter for the Energy dashboard on firmware that reports it.
- EVSE state sensor, and a single problem sensor for charger and vehicle faults.
- Per-phase voltage, current and power sensors, and DLM and IPM meter readings.
- Binary sensors for car connected and charging in progress.
- A `session_finished` event with the totals of every charging session.
- Switches for start/stop, autostart, display, LEDs, buzzer, out of service and forced single-phase charging.
- Number entities for the charging current limit and the load-management and grid-control parameters.
- Selects for the load-management mode and access mode.
- Buttons to reboot the charger and to run RFID learn mode.
- Services for the display, the rear LED and RFID tag management.
- Diagnostics download with credentials and account identifiers redacted.
- mDNS auto-discovery.
- English and Hungarian translations.

## Requirements

- Home Assistant 2025.1 or newer.
- [HACS](https://www.hacs.xyz/docs/use/download/download/) installed.
- A Voltie Charger on your LAN with HTTP API enabled in the Voltie mobile app. If you set a username and password, you'll need them during setup.

## Installation 📦

HACS is the recommended way: it handles updates for you.

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

Set a username and password for the HTTP API in the Voltie mobile app. Without them, anyone on your network can read and control the charger.

## Entities

Each charger creates one device with about 60 entities. The main ones:

| Entity | Purpose |
| --- | --- |
| `sensor.<name>_charge_power` | Live charging power (kW). |
| `sensor.<name>_session_energy` | Session energy (kWh). |
| `sensor.<name>_total_energy` | Lifetime energy meter (kWh), on firmware that reports it. |
| `sensor.<name>_session_charge_time` | Session charge time. |
| `sensor.<name>_evse_state` | EVSE state. |
| `sensor.<name>_active_phases` | Phases used by the current session. |
| `sensor.<name>_phases_wired` | Phases wired into the charger. |
| `sensor.<name>_hardware_current_limit` | Highest current the hardware supports (A). |
| `binary_sensor.<name>_car_connected` | Plug detection. |
| `binary_sensor.<name>_charging` | Charging in progress. |
| `binary_sensor.<name>_problem` | On while the charger or the vehicle reports a fault. |
| `event.<name>_charging_session` | Fires `session_finished` when a session ends. |
| `switch.<name>_charging_enabled` | Start / stop. |
| `switch.<name>_out_of_service` | Take the charger out of service. |
| `switch.<name>_force_single_phase_charging` | Force single-phase charging. |
| `number.<name>_maximum_charging_current` | Charging current limit (A). |
| `select.<name>_load_management_mode` | Off / dynamic / eco / green / grid control. |
| `select.<name>_access_mode` | Home charger, with or without RFID. |
| `button.<name>_reboot_charger` | Reboot the charger. |

Per-phase voltage / current / power, DLM / IPM readings, the grid-control parameters and the RFID reader status are exposed as individual entities. The per-phase, DLM and IPM sensors are diagnostic entities, disabled by default on new installs: enable them from the device page.

Entity IDs follow Home Assistant's language when an entity is first created. On a Hungarian system a new install gets IDs derived from the Hungarian names (for example `sensor.<name>_toltott_energia` rather than `sensor.<name>_session_energy`); existing entities keep their IDs.

`number.<name>_maximum_charging_current` takes its upper bound from the charger's own `current_hw_limit`, capped at the 32 A the API accepts.

`number.<name>_building_current_limit` goes up to 200 A, since 3×40 A and 3×63 A supplies are common. Firmware that still caps it at 32 A refuses higher values, and Home Assistant reports the refusal as an error.

The problem sensor ignores states that are not faults: out of service, starting up, waiting for a charging timer and firmware updates. The EVSE state sensor names the fault. It reads unknown before the charger's first valid reading and for a state code it does not know; the problem sensor still turns on for an unknown code.

The charger is polled every 30 seconds. For faster updates, see [Defining a custom polling interval](https://www.home-assistant.io/common-tasks/general/#defining-a-custom-polling-interval).

## Energy dashboard

Use `sensor.<name>_total_energy` when the charger provides it. It is a lifetime counter, which is what the Energy dashboard expects. No charger firmware reports it yet; the sensor appears by itself after the charger updates to one that does. On chargers without a MID meter the reading may only advance when a session ends, so the dashboard books the whole session in the hour it ends.

Until then, `sensor.<name>_session_energy` works: it reads 0 kWh between sessions, so its statistics stay continuous even across long breaks.

## Automations

`event.<name>_charging_session` fires `session_finished` once per session, when the car is unplugged. Its attributes carry the final figures from the charger's own record: `energy_kwh`, `charge_time_s`, `idle_time_s`, `avg_power_kw`, `max_power_kw`, `idtag_name`, `cdr_id`, `session_start` and `session_end`. `closed_after_restart` is true when a charger restart cut the session short.

```yaml
triggers:
  - trigger: state
    entity_id: event.<name>_charging_session
    not_from: unavailable
actions:
  - action: notify.notify
    data:
      message: >-
        Charged {{ trigger.to_state.attributes.energy_kwh or 0 }} kWh in
        {{ ((trigger.to_state.attributes.charge_time_s or 0) / 60) | round }}
        minutes.
```

A session that ends while Home Assistant is offline is reported once it is back; `session_end` tells when it actually ended. To act when the car stops drawing power rather than when it is unplugged, trigger on `binary_sensor.<name>_charging` turning off.

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

Each action targets one charger device. The RFID actions require API v5 firmware. Some fields change in the built-in integration, see [Actions that change](#actions-that-change).

**RFID tag IDs must be hexadecimal** (0-9, A-F), 8 to 20 characters. The API documentation describes a wider character set, but the firmware rejects anything else, so these actions validate it up front rather than letting the charger return a generic error.

## Upgrading from v0.4.0 or older

v0.5.0 re-keys the entities of v0.4.0, v0.3.0 and older on the first start. Entity IDs, history, names and other settings stay. Update the card to v0.5.0 first.

Entities have been keyed to the charger rather than to the config entry since v0.4.0, so a charger that is removed and added again gets its entities back, with their entity IDs, names and other customisations.

## Upgrading from v0.2.x

Existing entities keep their entity IDs, so dashboards and automations continue to work. Two cosmetic details are worth knowing:

- The `phases` sensor was renamed to **Phases wired**, because the API clarified that the field means phases wired into the charger rather than phases in use. On an upgraded install it keeps its original `..._phases_in_use` entity ID, so that ID no longer matches its name. The new session-phase sensor is **Active phases**.
- New entities may pick up an area prefix in their entity ID (for example `sensor.garage_voltie_charger_1234_active_phases`) while pre-existing ones do not, because Home Assistant derives IDs from the device's area at creation time. Removing and re-adding the integration gives a consistent set, at the cost of losing entity history.

## Firmware compatibility

The integration adapts to what the charger reports:

- Configuration entities whose `/config` key is missing read as unavailable.
- RFID entities are only created when the charger answers `GET /rfid/status`, and the lifetime energy sensor only when `/status` reports the reading. Firmware older than HTTP API v5 has no RFID endpoints. Chargers update their firmware on their own from the Voltie cloud.
- When the charger's software version changes, the integration reloads itself, so entities that a firmware update enables appear without a restart.
- `/extras` commands that the firmware rejects as unknown produce an error telling you to update the charger.

The diagnostics download reports the charger's major API version, which is useful in support tickets.

## Troubleshooting 🛠️

**Authentication fails.** The credentials are the ones set in the Voltie app under Settings > Advanced settings > Integrations > HTTP API, not your Voltie cloud account.

**Charger not discovered.** Confirm the HTTP API is enabled. Add the charger manually by IP if your network blocks mDNS.

**Entities go `unavailable`.** The integration retries with backoff. If it persists, check the charger is powered and on the network.

**RFID entities are missing.** They need API v5 firmware. The diagnostics download shows the API version. They appear by themselves once the charger has updated.

**A second set of entities after an update.** Entities ending in `_2` appear when old ones could not be re-keyed, for example after going back to an older release. The log names the entities it skipped. Remove the ones that stay unavailable.

**"Not master" errors on RFID actions.** The charger is a secondary unit in a prepaid-RFID cluster: send the action to the master unit instead.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

## License

Apache License 2.0, the same licence as Home Assistant. Copyright 2026 Voltie. See [LICENSE](LICENSE).
