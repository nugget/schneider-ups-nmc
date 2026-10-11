"""Tests for APC UPS NMC syslog parsing."""

from __future__ import annotations

import unittest
from datetime import datetime
from typing import TYPE_CHECKING, cast

from custom_components.schneider_ups_nmc import syslog

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class ParseSyslogMessageTest(unittest.TestCase):
    """Test NMC syslog message parsing."""

    def test_defines_default_listener_settings(self) -> None:
        """Expose the default local syslog listener settings."""
        self.assertEqual(syslog.DEFAULT_SYSLOG_BIND_ADDRESS, "0.0.0.0")
        self.assertTrue(syslog.DEFAULT_SYSLOG_ENABLED)
        self.assertFalse(syslog.DEFAULT_SYSLOG_LOG_RAW_MESSAGES)
        self.assertEqual(syslog.DEFAULT_SYSLOG_PORT, 1514)

    def test_parses_nmc3_test_message(self) -> None:
        """Parse the RFC5424-ish NMC3 syslog test format."""
        event = syslog.parse_syslog_message(
            "<8>1 2026-05-25T01:20:40-05:00 "
            "ups.example.test su_v2.5.5.1 System TEST - APC: Test Syslog."
        )

        self.assertEqual(event.priority, 8)
        self.assertEqual(event.facility, "user")
        self.assertEqual(event.severity, "emergency")
        self.assertEqual(event.hostname, "ups.example.test")
        self.assertEqual(event.app_name, "su_v2.5.5.1")
        self.assertEqual(event.proc_id, "System")
        self.assertEqual(event.msg_id, "TEST")
        self.assertEqual(event.structured_data, "-")
        self.assertEqual(event.event_category, "System TEST")
        self.assertEqual(event.event_text, "APC: Test Syslog.")
        self.assertEqual(event.structured_data_elements, ())

    def test_parses_rfc5424_structured_data_parameters(self) -> None:
        """Parse NMC RFC5424 structured data without leaking it into message."""
        event = syslog.parse_syslog_message(
            "<14>1 2026-05-26T16:59:45-05:00 "
            "ups-hor-rack.hollowoak.net su_v2.5.5.1 System 0x0073 "
            '[meta sequenceId="6" sysUpTime="6441"] '
            "Connected to UDP syslog server at homeassistant.hollowoak.net"
        )

        self.assertEqual(event.priority, 14)
        self.assertEqual(event.facility, "user")
        self.assertEqual(event.severity, "informational")
        self.assertEqual(event.hostname, "ups-hor-rack.hollowoak.net")
        self.assertEqual(event.proc_id, "System")
        self.assertEqual(event.msg_id, "0x0073")
        self.assertEqual(
            event.structured_data,
            '[meta sequenceId="6" sysUpTime="6441"]',
        )
        self.assertEqual(
            event.structured_data_elements,
            (
                syslog.SyslogStructuredDataElement(
                    element_id="meta",
                    parameters={
                        "sequenceId": "6",
                        "sysUpTime": "6441",
                    },
                ),
            ),
        )
        self.assertEqual(
            event.event_text,
            "Connected to UDP syslog server at homeassistant.hollowoak.net",
        )
        self.assertEqual(event.event_category, "System 0x0073")

    def test_parses_rfc5424_structured_data_quoted_escapes(self) -> None:
        """Parse quoted structured data parameters with spaces and escapes."""
        event = syslog.parse_syslog_message(
            "<14>1 2026-05-26T16:59:45-05:00 "
            "ups.example.test su_v2.5.5.1 Device 0x1234 "
            '[probe name="Top of Rack" detail="quoted \\"rack\\" \\] value"] '
            "Probe metadata changed"
        )

        self.assertEqual(
            event.structured_data_elements,
            (
                syslog.SyslogStructuredDataElement(
                    element_id="probe",
                    parameters={
                        "name": "Top of Rack",
                        "detail": 'quoted "rack" ] value',
                    },
                ),
            ),
        )
        self.assertEqual(event.event_text, "Probe metadata changed")

    def test_parses_rfc5424_multiple_structured_data_elements(self) -> None:
        """Parse adjacent structured data elements as separate elements."""
        cases = (
            (
                "two elements with parameters",
                '[meta sequenceId="7"][origin ip="192.0.2.10"]',
                (
                    syslog.SyslogStructuredDataElement(
                        element_id="meta",
                        parameters={"sequenceId": "7"},
                    ),
                    syslog.SyslogStructuredDataElement(
                        element_id="origin",
                        parameters={"ip": "192.0.2.10"},
                    ),
                ),
            ),
            (
                "element without parameters before another element",
                '[flag][meta sysUpTime="6441"]',
                (
                    syslog.SyslogStructuredDataElement(
                        element_id="flag",
                        parameters={},
                    ),
                    syslog.SyslogStructuredDataElement(
                        element_id="meta",
                        parameters={"sysUpTime": "6441"},
                    ),
                ),
            ),
            (
                "closing bracket inside quoted value",
                '[probe name="Rack ] Top"][meta sequenceId="8"]',
                (
                    syslog.SyslogStructuredDataElement(
                        element_id="probe",
                        parameters={"name": "Rack ] Top"},
                    ),
                    syslog.SyslogStructuredDataElement(
                        element_id="meta",
                        parameters={"sequenceId": "8"},
                    ),
                ),
            ),
        )

        for name, structured_data, expected_elements in cases:
            with self.subTest(name):
                event = syslog.parse_syslog_message(
                    "<14>1 2026-05-26T16:59:45-05:00 "
                    f"ups.example.test su_v2.5.5.1 Device 0x1234 "
                    f"{structured_data} Probe metadata changed"
                )

                self.assertEqual(event.structured_data, structured_data)
                self.assertEqual(event.structured_data_elements, expected_elements)
                self.assertEqual(event.event_text, "Probe metadata changed")

    def test_parses_rfc5424_messages_without_structured_data(self) -> None:
        """Accept RFC5424-like NMC messages that omit structured data."""
        event = syslog.parse_syslog_message(
            "<14>1 2026-05-26T16:59:45-05:00 "
            "ups.example.test su_v2.5.5.1 Device 0x1234 Probe connected"
        )

        self.assertEqual(event.structured_data, "-")
        self.assertEqual(event.structured_data_elements, ())
        self.assertEqual(event.event_text, "Probe connected")

    def test_parses_rfc3164_message(self) -> None:
        """Parse legacy RFC3164 syslog messages from known hosts."""
        current_year = datetime.now().year
        event = syslog.parse_syslog_message(
            "<13>May 25 17:45:00 ups.example.test APC: Test Syslog."
        )

        self.assertEqual(event.priority, 13)
        self.assertEqual(event.facility, "user")
        self.assertEqual(event.severity, "notice")
        self.assertEqual(event.timestamp.year, current_year)
        self.assertEqual(event.timestamp.month, 5)
        self.assertEqual(event.timestamp.day, 25)
        self.assertIsNotNone(event.timestamp.tzinfo)
        self.assertEqual(
            event.timestamp.isoformat(),
            f"{current_year}-05-25T17:45:00+00:00",
        )
        self.assertEqual(event.hostname, "ups.example.test")
        self.assertEqual(event.app_name, "-")
        self.assertIsNone(event.event_category)
        self.assertEqual(event.event_text, "APC: Test Syslog.")

    def test_rejects_invalid_rfc5424_timestamp_as_parse_error(self) -> None:
        """Wrap invalid RFC5424 timestamps in the syslog parse exception."""
        with self.assertRaisesRegex(
            syslog.SyslogParseError,
            "Invalid RFC5424 syslog timestamp",
        ):
            syslog.parse_syslog_message(
                "<8>1 not-a-timestamp "
                "ups.example.test su_v2.5.5.1 System TEST - APC: Test Syslog."
            )

    def test_rejects_invalid_rfc3164_timestamp_as_parse_error(self) -> None:
        """Wrap invalid RFC3164 timestamps in the syslog parse exception."""
        with self.assertRaisesRegex(
            syslog.SyslogParseError,
            "Invalid RFC3164 syslog timestamp",
        ):
            syslog.parse_syslog_message(
                "<13>Foo 25 17:45:00 ups.example.test APC: Test Syslog."
            )

    def test_defines_event_types_from_syslog_severities(self) -> None:
        """Expose syslog severities as Home Assistant event types."""
        self.assertEqual(
            syslog.SYSLOG_EVENT_TYPES,
            (
                "emergency",
                "alert",
                "critical",
                "error",
                "warning",
                "notice",
                "informational",
                "debug",
            ),
        )

    def test_routes_datagram_by_packet_source_host(self) -> None:
        """Route parsed events to the coordinator registered for source IP."""
        coordinator = _FakeCoordinator(host="192.0.2.10")

        dispatch = syslog.route_syslog_datagram(
            b"<8>1 2026-05-25T01:20:40-05:00 "
            b"ups.example.test su_v2.5.5.1 System TEST - APC: Test Syslog.",
            source_host="192.0.2.10",
            source_port=514,
            coordinators_by_host={coordinator.host: coordinator},
        )

        self.assertIsNotNone(dispatch)
        assert dispatch is not None
        self.assertIs(dispatch.coordinator, coordinator)
        self.assertEqual(dispatch.event.source_host, "192.0.2.10")
        self.assertEqual(dispatch.event.event.event_category, "System TEST")

    def test_routes_ipv4_mapped_ipv6_packet_sources(self) -> None:
        """Route IPv4 packets received by an IPv6 listener to the IPv4 host."""
        coordinator = _FakeCoordinator(host="192.0.2.10")

        dispatch = syslog.route_syslog_datagram(
            b"<8>1 2026-05-25T01:20:40-05:00 "
            b"ups.example.test su_v2.5.5.1 System TEST - APC: Test Syslog.",
            source_host="::ffff:192.0.2.10",
            source_port=514,
            coordinators_by_host={coordinator.host: coordinator},
        )

        self.assertIsNotNone(dispatch)
        assert dispatch is not None
        self.assertIs(dispatch.coordinator, coordinator)
        self.assertEqual(dispatch.event.source_host, "::ffff:192.0.2.10")

    def test_builds_home_assistant_event_state_data(self) -> None:
        """Build stable Home Assistant state data for a routed syslog event."""
        routed_event = syslog.RoutedSyslogEvent(
            source_host="192.0.2.10",
            source_port=514,
            event=syslog.parse_syslog_message(
                "<8>1 2026-05-25T01:20:40-05:00 "
                "ups.example.test su_v2.5.5.1 System TEST - APC: Test Syslog."
            ),
        )

        self.assertEqual(
            syslog.syslog_event_state_data(routed_event),
            {
                "source_host": "192.0.2.10",
                "source_port": 514,
                "priority": 8,
                "facility": "user",
                "severity": "emergency",
                "hostname": "ups.example.test",
                "app_name": "su_v2.5.5.1",
                "proc_id": "System",
                "msg_id": "TEST",
                "timestamp": "2026-05-25T01:20:40-05:00",
                "message": "APC: Test Syslog.",
                "category": "System TEST",
            },
        )

    def test_builds_structured_home_assistant_event_state_data(self) -> None:
        """Include parsed structured data elements in Home Assistant event data."""
        routed_event = syslog.RoutedSyslogEvent(
            source_host="192.0.2.10",
            source_port=514,
            event=syslog.parse_syslog_message(
                "<14>1 2026-05-26T16:59:45-05:00 "
                "ups-hor-rack.hollowoak.net su_v2.5.5.1 System 0x0073 "
                '[meta sequenceId="6" sysUpTime="6441"] '
                "Connected to UDP syslog server at homeassistant.hollowoak.net"
            ),
        )

        state_data = syslog.syslog_event_state_data(routed_event)

        self.assertEqual(
            state_data["structured_data"],
            '[meta sequenceId="6" sysUpTime="6441"]',
        )
        self.assertEqual(
            state_data["structured_data_elements"],
            [
                {
                    "id": "meta",
                    "parameters": {
                        "sequenceId": "6",
                        "sysUpTime": "6441",
                    },
                },
            ],
        )
        self.assertEqual(
            state_data["message"],
            "Connected to UDP syslog server at homeassistant.hollowoak.net",
        )

    def test_event_state_data_omits_empty_optional_fields(self) -> None:
        """Omit absent category and empty structured data from event state data."""
        routed_event = syslog.RoutedSyslogEvent(
            source_host="192.0.2.10",
            source_port=514,
            event=syslog.parse_syslog_message(
                "<14>1 2026-05-25T01:20:40-05:00 "
                "ups.example.test su_v2.5.5.1 - - - APC: No category."
            ),
        )

        state_data = syslog.syslog_event_state_data(routed_event)

        self.assertNotIn("category", state_data)
        self.assertNotIn("structured_data", state_data)
        self.assertEqual(state_data["severity"], "informational")

    def test_ignores_unknown_source_host_without_parsing(self) -> None:
        """Ignore unregistered source hosts before parsing the datagram."""
        dispatch = syslog.route_syslog_datagram(
            b"not syslog",
            source_host="192.0.2.99",
            source_port=514,
            coordinators_by_host={"192.0.2.10": _FakeCoordinator("192.0.2.10")},
        )

        self.assertIsNone(dispatch)

    def test_rejects_malformed_datagram_from_known_source_host(self) -> None:
        """Raise parse errors for configured hosts with malformed messages."""
        with self.assertRaises(syslog.SyslogParseError):
            syslog.route_syslog_datagram(
                b"not syslog",
                source_host="192.0.2.10",
                source_port=514,
                coordinators_by_host={"192.0.2.10": _FakeCoordinator("192.0.2.10")},
            )


class SyslogPushManagerTest(unittest.TestCase):
    """Test syslog push manager listener configuration helpers."""

    def test_reports_listener_configuration(self) -> None:
        """Report whether the manager matches requested listener settings."""
        manager = syslog.SyslogPushManager(
            cast("HomeAssistant", object()),
            bind_address="127.0.0.1",
            port=1515,
        )

        self.assertTrue(manager.is_idle)
        self.assertTrue(manager.is_configured_for("127.0.0.1", 1515))
        self.assertFalse(manager.is_configured_for("0.0.0.0", 1515))
        self.assertFalse(manager.is_configured_for("127.0.0.1", 1514))

    def test_records_parse_failures_from_known_sources(self) -> None:
        """Record unparsable datagrams from configured source hosts."""
        coordinator = _FakeCoordinator("192.0.2.10")
        manager = syslog.SyslogPushManager(cast("HomeAssistant", object()))
        manager._coordinators_by_host[coordinator.host] = coordinator

        manager._handle_datagram(b"not syslog", "::ffff:192.0.2.10", 514)

        self.assertEqual(len(coordinator.parse_failures), 1)
        self.assertEqual(
            coordinator.parse_failures[0],
            syslog.RoutedSyslogParseFailure(
                source_host="::ffff:192.0.2.10",
                source_port=514,
                error="Unsupported syslog message format",
            ),
        )

    def test_logs_received_datagrams_when_explicit_capture_is_enabled(self) -> None:
        """Log raw syslog datagrams for configured hosts when capture is enabled."""
        coordinator = _FakeCoordinator(
            "192.0.2.10",
            syslog_log_raw_messages=True,
        )
        manager = syslog.SyslogPushManager(cast("HomeAssistant", object()))
        manager._coordinators_by_host[coordinator.host] = coordinator

        with self.assertLogs(
            "custom_components.schneider_ups_nmc.syslog",
            level="INFO",
        ) as logs:
            manager._handle_datagram(b"not syslog\r\ninvalid \xff", "192.0.2.10", 514)

        self.assertEqual(len(coordinator.parse_failures), 1)
        self.assertEqual(
            logs.output,
            [
                (
                    "INFO:custom_components.schneider_ups_nmc.syslog:"
                    r"Received syslog datagram from 192.0.2.10:514: "
                    r"not syslog\r\ninvalid \xff"
                ),
            ],
        )


class _FakeCoordinator:
    """Minimal coordinator for syslog routing tests."""

    def __init__(self, host: str, *, syslog_log_raw_messages: bool = False) -> None:
        """Initialize the fake coordinator."""
        self.host = host
        self.syslog_log_raw_messages = syslog_log_raw_messages
        self.parse_failures: list[syslog.RoutedSyslogParseFailure] = []

    async def async_handle_syslog_event(
        self,
        event: object,
    ) -> None:
        """Handle a routed syslog event."""

    def async_handle_syslog_parse_failure(
        self,
        failure: syslog.RoutedSyslogParseFailure,
    ) -> None:
        """Record a syslog parse failure."""
        self.parse_failures.append(failure)


if __name__ == "__main__":
    unittest.main()
