# APC UPS NMC

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://www.hacs.xyz/)
[![CI](https://img.shields.io/github/actions/workflow/status/nugget/schneider-ups-nmc/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/nugget/schneider-ups-nmc/actions/workflows/ci.yml)
[![Manifest version](https://img.shields.io/badge/dynamic/json?style=flat-square&label=manifest&query=%24.version&url=https%3A%2F%2Fraw.githubusercontent.com%2Fnugget%2Fschneider-ups-nmc%2Fmain%2Fcustom_components%2Fschneider_ups_nmc%2Fmanifest.json)](https://github.com/nugget/schneider-ups-nmc/blob/main/custom_components/schneider_ups_nmc/manifest.json)
[![Release](https://img.shields.io/github/v/release/nugget/schneider-ups-nmc?style=flat-square&label=release)](https://github.com/nugget/schneider-ups-nmc/releases)
[![License](https://img.shields.io/github/license/nugget/schneider-ups-nmc?style=flat-square)](https://github.com/nugget/schneider-ups-nmc/blob/main/LICENSE)

APC UPS NMC is a local-first Home Assistant custom integration for APC by
Schneider Electric UPS units with Network Management Cards.

The integration uses SNMP polling as the source of truth for UPS telemetry and
can optionally listen for local syslog push events from one or more NMC cards.
Current support is developed and tested against NMC3 hardware while the
repository and Home Assistant domain leave room for additional Schneider
Electric/APC Network Management Card generations.

The integration is read-only. It exposes UPS identity, battery, input, output,
load, energy, self-test, replacement, alarm, and syslog event data from the
RFC1628 UPS-MIB plus Schneider Electric APC PowerNet MIB fields where useful.

## Supported Devices

Known supported hardware:

- APC by Schneider Electric UPS units with an NMC3 card and SNMP enabled.

Expected but not yet validated:

- Other APC by Schneider Electric NMC generations that expose the same RFC1628
  and PowerNet MIB values.

Not currently supported:

- UPS devices that only expose USB, Modbus, cloud APIs, or serial protocols.
- Multi-phase or multi-output modeling beyond the first input/output table row.

The first telemetry pass queries line index `1` for input and output table
values. That matches common single-phase UPS deployments. Multi-phase and
multi-output UPS support should grow from real NMC walks so the entity model
matches what the card actually reports.

## Requirements

- Home Assistant with HACS installed.
- An APC by Schneider Electric UPS with a supported Network Management Card.
- SNMP enabled on the NMC web or CLI interface.
- Either SNMPv2c read-only community access or SNMPv3 credentials.

SNMPv3 is preferred. If you use SNMPv2c, use a read-only community and restrict
the NMC access control list to your Home Assistant host.

## Installation

1. Add this repository as a custom integration repository in HACS.
2. Install **APC UPS NMC**.
3. Restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration**.
5. Search for **APC UPS NMC**.
6. Enter the NMC host, SNMP port, SNMP version, scan interval, and optional web
   UI URL.
7. Enter the SNMP credentials on the next setup page.

The setup flow validates the SNMP settings before creating an entry. SNMP
community strings and SNMPv3 passphrases are entered as password fields in Home
Assistant, and diagnostics redact stored SNMP secrets before they are exposed
for support.

Each UPS/NMC card should be added as its own integration entry with its own
host or IP address. The integration uses the UPS identity learned from SNMP to
avoid duplicate entries and to protect reconfiguration from accidentally
pointing an existing Home Assistant device at a different UPS.

## Configuration

Setup fields:

- **Host**: DNS name or IP address of the NMC SNMP interface.
- **Port**: SNMP UDP port. The default is `161`.
- **SNMP version**: `SNMPv2c` or `SNMPv3`.
- **Scan interval**: polling interval in seconds. The default is `60`.
- **Web UI URL**: optional hostname or HTTP(S) URL used for the Home Assistant
  device configuration link. Bare hostnames are treated as HTTPS. Paths, query
  strings, and path parameters are allowed for NMC deep links; URL fragments
  and embedded credentials are rejected.

SNMPv2c credential fields:

- **Community**: read-only SNMP community string.

SNMPv3 credential fields:

- **Username**
- **Authentication protocol**: SHA, MD5, or no authentication.
- **Authentication passphrase**
- **Privacy protocol**: AES, DES, or no privacy.
- **Privacy passphrase**

SNMPv3 privacy requires authentication. The setup flow reports a field error if
the selected protocol combination is invalid.

After setup, use **Reconfigure** from the integration entry to change the NMC
host, SNMP port, SNMP version, SNMP credentials, scan interval, or web UI URL
without deleting and re-adding the device.

Options fields:

- **Scan interval**
- **Enable syslog listener**
- **Syslog bind address**
- **Syslog UDP port**
- **Log received syslog messages**
- **Web UI URL**

The polling interval and syslog listener settings can be adjusted from options
without replacing the SNMP connection identity stored in the config entry.

## Data Updates

SNMP polling is the source of truth for all telemetry entities. Every poll
builds one coherent UPS snapshot through Home Assistant's data update
coordinator, and entities report unavailable when their backing value is absent
or the NMC cannot be reached.

Syslog is an optional local push companion. When a configured NMC sends a
supported syslog event, Home Assistant fires the integration's syslog event
entity and immediately requests a fresh SNMP poll. The syslog event itself is
useful for automations and troubleshooting, but it does not replace SNMP as the
authoritative state source.

The syslog parser accepts the RFC5424-style format emitted by NMC3 test/events
and a legacy RFC3164-style format. RFC3164 messages do not include a timezone,
so the integration stores them using the current year and UTC.

## Entities

Sensor entities:

- **Battery status**: enum such as `normal`, `low`, `depleted`, `fault`, or
  `no_battery_present`.
- **UPS status**: enum such as `online`, `on_battery`, `eco_mode`, `self_test`,
  and other PowerNet UPS states.
- **Battery charge**, **Estimated runtime**, **Seconds on battery**.
- **Battery voltage**, **Battery current**, **Battery temperature**.
- **Battery replacement status**, **Battery pack count**, **Battery SKUs**,
  **Battery last replaced**, and **Battery recommended replacement**.
- **Input voltage**, **Input frequency**, **Input current**, **Input power**,
  **Input line faults**, and **Last input transfer reason**.
- **Output source**, **Output voltage**, **Output frequency**,
  **Output current**, **Output power**, **Output apparent power**,
  **Output power factor**, **Output load**, **Output efficiency**, and
  **Output energy**.
- **Environmental probe temperature** for AP9335T/AP9335TH sensors attached to
  NMC universal I/O ports, plus **Environmental probe humidity** when the probe
  reports humidity.
- **Self-test result** and **Last self-test**.
- **Alarm count**.

Binary sensor entities:

- **On battery**
- **Battery low**
- **Battery needs replacing**
- **Alarm present**

Event entities:

- **Syslog event**: event type is the syslog severity. Event data includes the
  NMC message, category when available, facility, timestamp, and packet source.

Several diagnostic or low-use entities are disabled by default to keep the
entity registry focused. Entities whose backing OID is not exposed by a
particular UPS model or firmware report unavailable rather than presenting a
fresh but ambiguous unknown value.

## Actions

This integration does not currently register Home Assistant service actions. It
is read-only and reports UPS/NMC state for dashboards, automations, diagnostics,
and energy monitoring.

## Example Use Cases

Notify when protected equipment is running on battery:

```yaml
automation:
  - alias: UPS on battery
    triggers:
      - trigger: state
        entity_id: binary_sensor.rack_ups_on_battery
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: Rack UPS is running on battery.
```

React to a pushed NMC syslog event:

```yaml
automation:
  - alias: UPS warning syslog event
    triggers:
      - trigger: state
        entity_id: event.rack_ups_syslog_event
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.event_type == 'warning' }}"
    actions:
      - action: persistent_notification.create
        data:
          title: UPS warning
          message: "{{ trigger.to_state.attributes.message }}"
```

## Energy Dashboard

The **Output energy** sensor is reported in `kWh` with Home Assistant's energy
device class and `total_increasing` state class. When your NMC exposes that
counter, Home Assistant can use it in the Energy dashboard as an individual
device energy sensor.

Treat this value as protected-load energy measured at the UPS output. If you
also monitor the upstream circuit that feeds the UPS, add the UPS output energy
as an individual device under that upstream device in Home Assistant's energy
configuration so the same consumption is not counted twice.

Some UPS/NMC firmware may not expose the output energy counter. In that case
the **Output energy** sensor will be unavailable, but the **Output power** sensor
can still be used with Home Assistant's Integration helper to estimate energy
from sampled power readings.

## Syslog Push Events

The integration opens a shared UDP syslog listener on port `1514` by default.
Configure one or more NMC cards to send syslog events to the Home Assistant host
on that port. Events are routed to configured UPS entries by packet source IP.
If Home Assistant listens on IPv6 and the OS reports an IPv4 sender as an
IPv4-mapped IPv6 address, the integration still routes the event to the matching
IPv4 NMC entry.

Because Home Assistant only needs one local syslog socket for all configured UPS
entries, every syslog-enabled entry should use the same listener settings. The
listener can be disabled or moved to another bind address and UDP port from the
integration options.

For parser development or support captures, enable **Log received syslog
messages** in the integration options. When enabled, the integration logs every
syslog datagram received from that configured NMC source to the Home Assistant
log. Leave this disabled during normal operation because syslog messages can
include local operational details such as usernames, hostnames, and event text.

If the listener cannot bind its configured address and port, if two
syslog-enabled entries request different listener settings, or if a configured
NMC sends syslog messages that cannot be parsed, the integration raises a Home
Assistant Repair issue with the settings or source that need attention.

## Device Registry

When the NMC exposes a physical network interface through IF-MIB, the
integration registers the NMC MAC address as a Home Assistant device
connection. That helps Home Assistant coalesce the UPS device with discovery or
future integrations that identify the same network card by MAC address.

The Home Assistant device registry entry also includes the NMC web
configuration URL derived from the configured SNMP host, plus manufacturer,
model, serial number, and firmware details when the NMC exposes them.

## Diagnostics

Diagnostics include redacted config entry data, current device identity, update
success state, available telemetry keys, the latest routed syslog event while it
is fresh, and syslog parse-failure counts. SNMP community strings and SNMPv3
credential fields are redacted before diagnostics are returned to Home
Assistant.

The latest syslog event in diagnostics is retained for 24 hours. It is intended
as a troubleshooting hint, not a durable event log.

## Troubleshooting

**The setup flow says it cannot connect.**
Verify the NMC host, SNMP port, SNMP version, credentials, NMC access control
list, and network path from Home Assistant to the NMC. Setup validates the SNMP
connection before it stores the config entry.

**An entity is unavailable.**
The NMC may not expose that OID for your UPS model or firmware, or the most
recent SNMP refresh may have failed. Check diagnostics and Home Assistant logs
for the integration.

**A battery or self-test date looks wrong.**
Some NMC firmware returns display-locale date strings over SNMP. Ambiguous slash
dates such as `01/02/2026` are interpreted US-first as January 2, 2026.
Year-first dates such as `2026-05-25` and `2026/05/25`, plus unambiguous
day-first dates such as `13/04/2026`, parse correctly.

**The syslog listener cannot start.**
Another process may already be using the configured UDP port, or multiple UPS
entries may have different syslog listener settings. Use the Repair issue or
the integration options to align the bind address and UDP port.

**Syslog messages could not be parsed.**
Check that the NMC is configured to send syslog in English and is using a
supported format. The integration currently accepts the NMC3 RFC5424-style
format and a legacy RFC3164-style format.

**Output energy is unavailable.**
Some UPS/NMC firmware does not expose the PowerNet output energy counter. Use
the **Output power** sensor with Home Assistant's Integration helper if you want
estimated energy from sampled power readings.

## Removal

1. In Home Assistant, go to **Settings > Devices & services**.
2. Open **APC UPS NMC**.
3. Delete each config entry you no longer want.
4. Remove or disable the matching syslog destination on the NMC if you enabled
   syslog push events.
5. Optionally uninstall the integration from HACS and restart Home Assistant.

## Release Engineering

`just release <version>` is the canonical release path. It updates release
metadata, runs the full local gate, creates a signed `v`-prefixed tag, pushes
the branch and tag, and creates a GitHub Release for HACS.

After the release exists on GitHub, replace the generated release notes with a
narrative release summary before announcing it. Start with a single top-level
`#` heading that describes the scope and spirit of the release rather than
repeating the tag. Let that heading set the tone; personality is welcome when it
helps the release feel written by humans. Explain why the release matters to
Home Assistant users, group changes by user impact, and keep PR links or the
full changelog as supporting detail rather than the whole story.

## License

APC UPS NMC is released under the [Apache License 2.0](LICENSE), matching Home
Assistant's source license.
