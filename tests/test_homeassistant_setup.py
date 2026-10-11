"""Home Assistant integration tests for APC UPS NMC."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    STATE_UNAVAILABLE,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.schneider_ups_nmc as integration
import custom_components.schneider_ups_nmc.coordinator as coordinator_module
import custom_components.schneider_ups_nmc.entity as entity_module
import custom_components.schneider_ups_nmc.event as event_module
from custom_components.schneider_ups_nmc.const import (
    CONF_COMMUNITY,
    CONF_SNMP_VERSION,
    CONF_SYSLOG_BIND_ADDRESS,
    CONF_SYSLOG_ENABLED,
    CONF_SYSLOG_PORT,
    CONF_WEB_URL,
    DOMAIN,
    TROUBLESHOOTING_URL,
)
from custom_components.schneider_ups_nmc.snmp import (
    SNMP_VERSION_2C,
    EnvironmentalProbe,
    SNMPError,
    UPSData,
)
from custom_components.schneider_ups_nmc.syslog import (
    RoutedSyslogEvent,
    RoutedSyslogParseFailure,
    parse_syslog_message,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant

    from custom_components.schneider_ups_nmc.coordinator import (
        SchneiderUPSNMCCoordinator,
    )

ENTRY_ID = "01HZZZZZZZZZZZZZZZZZZZZZZZ"
ENTRY_UNIQUE_ID = "ups-test-device"
pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def test_configuration_url_formats_ip_hosts() -> None:
    """Format NMC web configuration URLs for IP hosts."""
    assert entity_module._configuration_url("192.0.2.10") == "http://192.0.2.10"
    assert entity_module._configuration_url("2001:db8::1") == "http://[2001:db8::1]"
    assert entity_module._configuration_url("fe80::1%eth0") == "http://[fe80::1%25eth0]"
    assert (
        entity_module._configuration_url(
            "192.0.2.10",
            "https://ups.example.test:8443/status",
        )
        == "https://ups.example.test:8443/status"
    )
    assert (
        entity_module._configuration_url("192.0.2.10", "ups.example.test")
        == "https://ups.example.test"
    )
    assert entity_module._configuration_url("192.0.2.10", "   ") == "http://192.0.2.10"
    assert (
        entity_module._configuration_url("192.0.2.10", "https://host:invalid")
        == "http://192.0.2.10"
    )
    assert (
        entity_module._configuration_url("192.0.2.10", "https://host/path with space")
        == "http://192.0.2.10"
    )


def test_coordinator_expires_stale_syslog_diagnostic_event(
    hass: HomeAssistant,
) -> None:
    """Expire the latest syslog event after the diagnostics retention window."""
    coordinator = coordinator_module.SchneiderUPSNMCCoordinator(hass, _mock_entry())
    coordinator._last_syslog_event = RoutedSyslogEvent(
        source_host="192.0.2.10",
        source_port=514,
        event=parse_syslog_message(
            "<8>1 2026-05-25T01:20:40-05:00 "
            "ups.example.test su_v2.5.5.1 System TEST - APC: Test Syslog."
        ),
    )
    coordinator._last_syslog_event_received_at = (
        datetime.now(UTC)
        - coordinator_module.SYSLOG_EVENT_DIAGNOSTIC_TTL
        - timedelta(seconds=1)
    )

    assert coordinator.last_syslog_event is None
    assert coordinator._last_syslog_event is None

    coordinator.close()


def test_syslog_event_types_are_not_shared_mutable_state(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return HA event types without exposing mutable class-level state."""
    monkeypatch.setattr(coordinator_module, "SNMPClient", _FakeSNMPClient)
    coordinator = coordinator_module.SchneiderUPSNMCCoordinator(hass, _mock_entry())
    entity = event_module.SchneiderUPSNMCSyslogEventEntity(
        coordinator,
        event_module.SYSLOG_EVENT_DESCRIPTION,
    )

    event_types = entity.event_types
    event_types.append("custom")

    assert event_types != entity.event_types
    assert tuple(entity.event_types) == event_module.SYSLOG_EVENT_TYPES

    coordinator.close()


def test_coordinator_creates_syslog_parse_failure_repair_issue(
    hass: HomeAssistant,
) -> None:
    """Create a Repair issue when a known NMC sends unparsable syslog."""
    coordinator = coordinator_module.SchneiderUPSNMCCoordinator(hass, _mock_entry())

    coordinator.async_handle_syslog_parse_failure(
        RoutedSyslogParseFailure(
            source_host="192.0.2.10",
            source_port=514,
            error="Unsupported syslog message format",
        )
    )

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN,
        f"{coordinator_module.SYSLOG_PARSE_FAILURE_ISSUE}_{ENTRY_ID}",
    )
    assert issue is not None
    assert issue.is_fixable
    assert issue.learn_more_url == TROUBLESHOOTING_URL
    assert issue.data == {
        "entry_id": ENTRY_ID,
        "error": "Unsupported syslog message format",
        "name": "Rack UPS",
        "source": "192.0.2.10:514",
    }
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {
        "error": "Unsupported syslog message format",
        "name": "Rack UPS",
        "source": "192.0.2.10:514",
    }
    assert coordinator.syslog_parse_failure_count == 1

    coordinator.close()


def test_coordinator_formats_ipv6_syslog_parse_failure_source(
    hass: HomeAssistant,
) -> None:
    """Bracket IPv6 sources in syslog parse failure Repair placeholders."""
    coordinator = coordinator_module.SchneiderUPSNMCCoordinator(hass, _mock_entry())

    coordinator.async_handle_syslog_parse_failure(
        RoutedSyslogParseFailure(
            source_host="::ffff:192.0.2.10",
            source_port=514,
            error="Unsupported syslog message format",
        )
    )

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN,
        f"{coordinator_module.SYSLOG_PARSE_FAILURE_ISSUE}_{ENTRY_ID}",
    )
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["source"] == "[::ffff:192.0.2.10]:514"

    coordinator.close()


async def test_config_entry_sets_up_entities_and_unloads(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set up a config entry, create entities, and unload cleanly."""
    _FakeSNMPClient.instances.clear()
    monkeypatch.setattr(coordinator_module, "SNMPClient", _FakeSNMPClient)

    entry = _mock_entry(options={CONF_SYSLOG_ENABLED: False})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert _FakeSNMPClient.instances
    assert entry.runtime_data.client is _FakeSNMPClient.instances[0]
    assert ENTRY_ID not in hass.data.get(DOMAIN, {})
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{ENTRY_UNIQUE_ID}_battery_charge",
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "97"

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, ENTRY_UNIQUE_ID), entry.entry_id
    )
    assert device is not None
    assert device.configuration_url == "http://192.0.2.10"
    assert device.connections == {
        (dr.CONNECTION_NETWORK_MAC, "00:c0:b7:12:34:56"),
    }
    assert device.manufacturer == "Schneider Electric"
    assert device.model == "Smart-UPS 1500"
    assert device.serial_number == "AS1234567890"
    assert device.sw_version == "UPS 15.0 / NMC 3.2.1"

    missing_entity_id = er.async_get(hass).async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{ENTRY_UNIQUE_ID}_battery_temperature",
    )
    assert missing_entity_id is not None
    missing_state = hass.states.get(missing_entity_id)
    assert missing_state is not None
    assert missing_state.state == STATE_UNAVAILABLE

    await _assert_environmental_probe_entities_can_appear(hass, entry.runtime_data)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert _FakeSNMPClient.instances[0].closed
    assert not hasattr(entry, "runtime_data")


async def _assert_environmental_probe_entities_can_appear(
    hass: HomeAssistant,
    coordinator: SchneiderUPSNMCCoordinator,
) -> None:
    """Assert AP9335 environmental probe sensors are created dynamically."""
    front_temperature_entity_id = er.async_get(hass).async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{ENTRY_UNIQUE_ID}_environment_probe_1_1_temperature",
    )
    assert front_temperature_entity_id is not None
    front_temperature_state = hass.states.get(front_temperature_entity_id)
    assert front_temperature_state is not None
    assert front_temperature_state.state == "23"
    assert (
        front_temperature_state.attributes[ATTR_FRIENDLY_NAME]
        == "Rack UPS Rack front temperature"
    )

    front_humidity_entity_id = er.async_get(hass).async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{ENTRY_UNIQUE_ID}_environment_probe_1_1_humidity",
    )
    assert front_humidity_entity_id is None

    rear_humidity_entity_id = er.async_get(hass).async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{ENTRY_UNIQUE_ID}_environment_probe_2_1_humidity",
    )
    assert rear_humidity_entity_id is not None
    rear_humidity_state = hass.states.get(rear_humidity_entity_id)
    assert rear_humidity_state is not None
    assert rear_humidity_state.state == "42"

    data = coordinator.data
    assert data is not None
    coordinator.async_set_updated_data(
        replace(
            data,
            environmental_probes=(
                EnvironmentalProbe(
                    index="1.1",
                    name="Rack top",
                    location="Front",
                    connected=True,
                    temperature=23,
                    humidity=41,
                ),
                data.environmental_probes[1],
            ),
        )
    )
    await hass.async_block_till_done()

    front_humidity_entity_id = er.async_get(hass).async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{ENTRY_UNIQUE_ID}_environment_probe_1_1_humidity",
    )
    assert front_humidity_entity_id is not None
    front_humidity_state = hass.states.get(front_humidity_entity_id)
    assert front_humidity_state is not None
    assert front_humidity_state.state == "41"
    assert (
        front_humidity_state.attributes[ATTR_FRIENDLY_NAME]
        == "Rack UPS Rack top humidity"
    )

    front_temperature_state = hass.states.get(front_temperature_entity_id)
    assert front_temperature_state is not None
    assert (
        front_temperature_state.attributes[ATTR_FRIENDLY_NAME]
        == "Rack UPS Rack top temperature"
    )


async def test_config_entry_does_not_store_runtime_data_on_refresh_failure(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not retain a failed coordinator on setup retry paths."""
    _FailingSNMPClient.instances.clear()
    monkeypatch.setattr(coordinator_module, "SNMPClient", _FailingSNMPClient)

    entry = _mock_entry(options={CONF_SYSLOG_ENABLED: False})
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _FailingSNMPClient.instances[0].closed
    assert not hasattr(entry, "runtime_data")
    assert ENTRY_ID not in hass.data.get(DOMAIN, {})


async def test_config_entry_unloads_after_partial_setup_failure(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unload cleanly when setup fails after runtime data is assigned."""
    _FakeSNMPClient.instances.clear()
    monkeypatch.setattr(coordinator_module, "SNMPClient", _FakeSNMPClient)

    async def async_forward_entry_setups(*_args: object) -> None:
        """Simulate a platform setup failure."""
        raise RuntimeError("platform setup failed")

    async def async_unload_platforms(*_args: object) -> bool:
        """Simulate Home Assistant unloading any partially created platforms."""
        return True

    monkeypatch.setattr(
        hass.config_entries,
        "async_forward_entry_setups",
        async_forward_entry_setups,
    )
    monkeypatch.setattr(
        hass.config_entries,
        "async_unload_platforms",
        async_unload_platforms,
    )

    entry = _mock_entry(options={CONF_SYSLOG_ENABLED: False})
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert _FakeSNMPClient.instances[0].closed
    assert await integration.async_unload_entry(hass, entry)


async def test_config_entry_marks_missing_binary_value_unavailable(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mark binary sensors unavailable when their source value is absent."""
    _SparseSNMPClient.instances.clear()
    monkeypatch.setattr(coordinator_module, "SNMPClient", _SparseSNMPClient)

    entry = _mock_entry(options={CONF_SYSLOG_ENABLED: False})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor",
        DOMAIN,
        f"{ENTRY_UNIQUE_ID}_battery_low",
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _SparseSNMPClient.instances[0].closed


async def test_config_entry_uses_explicit_web_url(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use an explicit NMC web URL for the device configuration link."""
    _FakeSNMPClient.instances.clear()
    monkeypatch.setattr(coordinator_module, "SNMPClient", _FakeSNMPClient)

    entry = _mock_entry(
        options={
            CONF_SYSLOG_ENABLED: False,
            CONF_WEB_URL: "https://ups.example.test:8443/status",
        }
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, ENTRY_UNIQUE_ID), entry.entry_id
    )
    assert device is not None
    assert device.configuration_url == "https://ups.example.test:8443/status"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_syslog_register_failure_creates_and_clears_repair_issue(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create a Repair issue when the syslog listener cannot bind."""
    manager = _FailingSyslogManager()
    monkeypatch.setattr(
        integration,
        "_syslog_manager",
        _manager_factory(manager),
    )
    entry = _mock_entry(
        options={
            CONF_SYSLOG_BIND_ADDRESS: "127.0.0.1",
            CONF_SYSLOG_PORT: 1515,
        }
    )
    stale_parse_issue_id = f"{coordinator_module.SYSLOG_PARSE_FAILURE_ISSUE}_{ENTRY_ID}"
    registry = ir.async_get(hass)
    ir.async_create_issue(
        hass,
        DOMAIN,
        stale_parse_issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=coordinator_module.SYSLOG_PARSE_FAILURE_ISSUE,
    )

    await integration._async_register_syslog(
        hass,
        entry,
        cast("SchneiderUPSNMCCoordinator", object()),
    )

    issue = registry.async_get_issue(
        DOMAIN,
        f"{integration.SYSLOG_LISTENER_FAILED_ISSUE}_{ENTRY_ID}",
    )
    assert issue is not None
    assert issue.is_fixable
    assert issue.learn_more_url == TROUBLESHOOTING_URL
    assert issue.data == {
        "address": "127.0.0.1:1515",
        "entry_id": ENTRY_ID,
        "error": "address already in use",
        "name": "Rack UPS",
    }
    assert issue.translation_placeholders == {
        "address": "127.0.0.1:1515",
        "error": "address already in use",
        "name": "Rack UPS",
    }
    assert registry.async_get_issue(DOMAIN, stale_parse_issue_id) is None

    disabled_entry = _mock_entry(options={CONF_SYSLOG_ENABLED: False})
    await integration._async_register_syslog(
        hass,
        disabled_entry,
        cast("SchneiderUPSNMCCoordinator", object()),
    )

    assert (
        registry.async_get_issue(
            DOMAIN,
            f"{integration.SYSLOG_LISTENER_FAILED_ISSUE}_{ENTRY_ID}",
        )
        is None
    )


async def test_syslog_listener_conflict_creates_repair_issue(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create a Repair issue when entries request conflicting listener settings."""
    manager = _ConflictingSyslogManager()
    monkeypatch.setattr(
        integration,
        "_syslog_manager",
        _manager_factory(manager),
    )
    entry = _mock_entry(
        options={
            CONF_SYSLOG_BIND_ADDRESS: "127.0.0.1",
            CONF_SYSLOG_PORT: 1515,
        }
    )
    stale_parse_issue_id = f"{coordinator_module.SYSLOG_PARSE_FAILURE_ISSUE}_{ENTRY_ID}"
    registry = ir.async_get(hass)
    ir.async_create_issue(
        hass,
        DOMAIN,
        stale_parse_issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=coordinator_module.SYSLOG_PARSE_FAILURE_ISSUE,
    )

    await integration._async_register_syslog(
        hass,
        entry,
        cast("SchneiderUPSNMCCoordinator", object()),
    )

    issue = registry.async_get_issue(
        DOMAIN,
        f"{integration.SYSLOG_LISTENER_CONFLICT_ISSUE}_{ENTRY_ID}",
    )
    assert issue is not None
    assert issue.is_fixable
    assert issue.learn_more_url == TROUBLESHOOTING_URL
    assert issue.data == {
        "active": "0.0.0.0:1514",
        "entry_id": ENTRY_ID,
        "name": "Rack UPS",
        "requested": "127.0.0.1:1515",
    }
    assert registry.async_get_issue(DOMAIN, stale_parse_issue_id) is None
    assert issue.translation_placeholders == {
        "active": "0.0.0.0:1514",
        "name": "Rack UPS",
        "requested": "127.0.0.1:1515",
    }


async def test_update_listener_uses_config_entries_reload(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use Home Assistant's config-entry reload helper for options changes."""
    reloads: list[str] = []

    async def async_reload(entry_id: str) -> None:
        """Record the requested config-entry reload."""
        reloads.append(entry_id)

    monkeypatch.setattr(hass.config_entries, "async_reload", async_reload)
    entry = _mock_entry()

    await integration._async_update_listener(hass, entry)

    assert reloads == [ENTRY_ID]


def _mock_entry(
    *,
    options: Mapping[str, Any] | None = None,
) -> MockConfigEntry:
    """Return a representative config entry for HA setup tests."""
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        title="Rack UPS",
        unique_id=ENTRY_UNIQUE_ID,
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 161,
            CONF_SCAN_INTERVAL: 60,
            CONF_SNMP_VERSION: SNMP_VERSION_2C,
            CONF_COMMUNITY: "public",
        },
        options=dict(options or {}),
    )


def _manager_factory(
    manager: _FailingSyslogManager | _ConflictingSyslogManager,
) -> Any:
    """Return a fake syslog manager factory for integration setup."""

    def get_manager(
        _hass: HomeAssistant,
        *,
        bind_address: str,
        port: int,
    ) -> _FailingSyslogManager | _ConflictingSyslogManager:
        assert bind_address == "127.0.0.1"
        assert port == 1515
        return manager

    return get_manager


class _FakeSNMPClient:
    """SNMP client fake that returns stable UPS data."""

    instances: ClassVar[list[_FakeSNMPClient]] = []

    def __init__(self, config: object) -> None:
        """Initialize the fake SNMP client."""
        self.config = config
        self.closed = False
        self.instances.append(self)

    async def async_get_data(self) -> UPSData:
        """Return representative UPS data."""
        return UPSData(
            values={
                "alarm_count": 0,
                "battery_charge": 97,
                "battery_replace_indicator": "ok",
                "battery_status": "normal",
                "output_source": "normal",
                "seconds_on_battery": 0,
            },
            name="Rack UPS",
            manufacturer="Schneider Electric",
            model="Smart-UPS 1500",
            serial_number="AS1234567890",
            firmware_version="UPS 15.0 / NMC 3.2.1",
            agent_version="NMC 3.2.1",
            mac_address="00:c0:b7:12:34:56",
            unique_id=ENTRY_UNIQUE_ID,
            environmental_probes=(
                EnvironmentalProbe(
                    index="1.1",
                    name="Rack front",
                    location="Front",
                    connected=True,
                    temperature=23,
                    humidity=None,
                ),
                EnvironmentalProbe(
                    index="2.1",
                    name="Rack rear",
                    location="Rear",
                    connected=True,
                    temperature=25,
                    humidity=42,
                ),
            ),
        )

    def close(self) -> None:
        """Close the fake SNMP client."""
        self.closed = True


class _SparseSNMPClient(_FakeSNMPClient):
    """SNMP client fake that omits optional values."""

    instances: ClassVar[list[_SparseSNMPClient]] = []

    async def async_get_data(self) -> UPSData:
        """Return UPS data without battery status details."""
        return UPSData(
            values={
                "battery_charge": 97,
            },
            name="Rack UPS",
            manufacturer="Schneider Electric",
            model="Smart-UPS 1500",
            serial_number="AS1234567890",
            firmware_version="UPS 15.0 / NMC 3.2.1",
            agent_version="NMC 3.2.1",
            mac_address="00:c0:b7:12:34:56",
            unique_id=ENTRY_UNIQUE_ID,
        )


class _FailingSNMPClient(_FakeSNMPClient):
    """SNMP client fake that fails during the first refresh."""

    instances: ClassVar[list[_FailingSNMPClient]] = []

    async def async_get_data(self) -> UPSData:
        """Raise a representative SNMP failure."""
        raise SNMPError("timed out")


class _FailingSyslogManager:
    """Syslog manager fake that fails during registration."""

    bind_address = "127.0.0.1"
    port = 1515

    def is_configured_for(self, bind_address: str, port: int) -> bool:
        """Return whether the fake listener matches the requested settings."""
        return self.bind_address == bind_address and self.port == port

    async def async_register(self, _coordinator: object) -> None:
        """Fail to register a coordinator."""
        raise OSError("address already in use")


class _ConflictingSyslogManager:
    """Syslog manager fake that already owns different listener settings."""

    bind_address = "0.0.0.0"
    port = 1514

    def is_configured_for(self, _bind_address: str, _port: int) -> bool:
        """Return whether the fake listener matches the requested settings."""
        return False
