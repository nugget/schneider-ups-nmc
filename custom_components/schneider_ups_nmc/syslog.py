"""Syslog parsing for APC UPS NMC."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
DEFAULT_SYSLOG_BIND_ADDRESS = "0.0.0.0"
DEFAULT_SYSLOG_ENABLED = True
DEFAULT_SYSLOG_LOG_RAW_MESSAGES = False
DEFAULT_SYSLOG_PORT = 1514
RFC5424_HEADER_RE = re.compile(
    r"^<(?P<priority>\d+)>(?P<version>\d+) "
    r"(?P<timestamp>\S+) "
    r"(?P<hostname>\S+) "
    r"(?P<app_name>\S+) "
    r"(?P<proc_id>\S+) "
    r"(?P<msg_id>\S+)"
    r"(?: (?P<remainder>.*))?$"
)
RFC3164_RE = re.compile(
    r"^<(?P<priority>\d+)>(?P<timestamp>[A-Z][a-z]{2}\s+\d{1,2} "
    r"\d{2}:\d{2}:\d{2}) "
    r"(?P<hostname>\S+) "
    r"(?P<message>.*)$"
)

SEVERITY = {
    0: "emergency",
    1: "alert",
    2: "critical",
    3: "error",
    4: "warning",
    5: "notice",
    6: "informational",
    7: "debug",
}
SYSLOG_EVENT_TYPES = tuple(SEVERITY.values())

FACILITY = {
    0: "kernel",
    1: "user",
    2: "mail",
    3: "daemon",
    4: "auth",
    5: "syslog",
    6: "lpr",
    7: "news",
    8: "uucp",
    9: "clock",
    10: "authpriv",
    11: "ftp",
    12: "ntp",
    13: "audit",
    14: "alert",
    15: "cron",
    16: "local0",
    17: "local1",
    18: "local2",
    19: "local3",
    20: "local4",
    21: "local5",
    22: "local6",
    23: "local7",
}


class SyslogParseError(ValueError):
    """Raised when a syslog message cannot be parsed."""


@dataclass(frozen=True)
class SyslogStructuredDataElement:
    """A parsed RFC5424 structured data element."""

    element_id: str
    parameters: Mapping[str, str]


@dataclass(frozen=True)
class SyslogEvent:
    """A parsed NMC syslog event."""

    priority: int
    facility: str
    severity: str
    timestamp: datetime
    hostname: str
    app_name: str
    proc_id: str
    msg_id: str
    structured_data: str
    message: str
    event_category: str | None
    event_text: str
    structured_data_elements: tuple[SyslogStructuredDataElement, ...] = ()


@dataclass(frozen=True)
class RoutedSyslogEvent:
    """A syslog event with packet source metadata."""

    source_host: str
    source_port: int
    event: SyslogEvent


@dataclass(frozen=True)
class RoutedSyslogParseFailure:
    """An unparsable syslog datagram from a configured packet source."""

    source_host: str
    source_port: int
    error: str


@dataclass(frozen=True)
class SyslogDispatch:
    """A parsed syslog event matched to a configured coordinator."""

    coordinator: SyslogEventCoordinator
    event: RoutedSyslogEvent


class SyslogEventCoordinator(Protocol):
    """Coordinator protocol used by the syslog router."""

    host: str
    syslog_log_raw_messages: bool

    async def async_handle_syslog_event(self, event: RoutedSyslogEvent) -> None:
        """Handle a routed syslog event."""

    def async_handle_syslog_parse_failure(
        self,
        failure: RoutedSyslogParseFailure,
    ) -> None:
        """Handle an unparsable syslog datagram from this coordinator's NMC."""


class SyslogPushManager:
    """Shared UDP syslog listener for configured NMC devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        bind_address: str = DEFAULT_SYSLOG_BIND_ADDRESS,
        port: int = DEFAULT_SYSLOG_PORT,
    ) -> None:
        """Initialize the syslog push manager."""
        self._hass = hass
        self._bind_address = bind_address
        self._port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._coordinators_by_host: dict[str, SyslogEventCoordinator] = {}
        self._route_keys_by_host: dict[str, set[str]] = {}

    async def async_register(
        self,
        coordinator: SyslogEventCoordinator,
    ) -> Callable[[], None]:
        """Register a coordinator for syslog events from its NMC host."""
        route_keys = await self._async_route_keys(coordinator.host)
        await self._async_start()
        for route_key in route_keys:
            self._coordinators_by_host[route_key] = coordinator
        self._route_keys_by_host[coordinator.host] = route_keys

        def unregister() -> None:
            """Unregister a coordinator from the syslog listener."""
            for route_key in self._route_keys_by_host.pop(coordinator.host, set()):
                if self._coordinators_by_host.get(route_key) is coordinator:
                    self._coordinators_by_host.pop(route_key, None)
            if not self._coordinators_by_host:
                self.close()

        return unregister

    def close(self) -> None:
        """Close the syslog listener transport."""
        if self._transport is None:
            return

        self._transport.close()
        self._transport = None

    @property
    def is_idle(self) -> bool:
        """Return whether the listener has no active registrations."""
        return not self._coordinators_by_host

    @property
    def bind_address(self) -> str:
        """Return the syslog listener bind address."""
        return self._bind_address

    @property
    def port(self) -> int:
        """Return the syslog listener UDP port."""
        return self._port

    def is_configured_for(self, bind_address: str, port: int) -> bool:
        """Return whether the listener uses the requested bind address and port."""
        return self._bind_address == bind_address and self._port == port

    async def _async_start(self) -> None:
        """Start the UDP listener if it is not already running."""
        if self._transport is not None:
            return

        transport, _protocol = await self._hass.loop.create_datagram_endpoint(
            lambda: _SyslogUDPProtocol(self._handle_datagram),
            local_addr=(self._bind_address, self._port),
        )
        self._transport = transport

    async def _async_route_keys(self, host: str) -> set[str]:
        """Return hostnames and resolved addresses that may identify one NMC."""
        route_keys = syslog_route_keys(host)
        try:
            address_info = await self._hass.loop.getaddrinfo(
                host,
                None,
                type=socket.SOCK_DGRAM,
            )
        except OSError as err:
            _LOGGER.debug("Could not resolve syslog route host %s: %s", host, err)
            return route_keys

        for *_, socket_address in address_info:
            if socket_address:
                route_keys.update(syslog_route_keys(str(socket_address[0])))

        return route_keys

    def _handle_datagram(
        self,
        raw: bytes,
        source_host: str,
        source_port: int,
    ) -> None:
        """Route a syslog datagram to the matching coordinator."""
        coordinator = syslog_coordinator_for_source(
            source_host,
            self._coordinators_by_host,
        )
        if coordinator is not None and coordinator.syslog_log_raw_messages:
            _LOGGER.info(
                "Received syslog datagram from %s:%s: %s",
                source_host,
                source_port,
                _syslog_datagram_log_text(raw),
            )

        try:
            dispatch = route_syslog_datagram(
                raw,
                source_host=source_host,
                source_port=source_port,
                coordinators_by_host=self._coordinators_by_host,
            )
        except SyslogParseError as err:
            if coordinator is not None:
                coordinator.async_handle_syslog_parse_failure(
                    RoutedSyslogParseFailure(
                        source_host=source_host,
                        source_port=source_port,
                        error=str(err),
                    )
                )
            _LOGGER.debug(
                "Ignoring unparsable syslog datagram from %s:%s: %s",
                source_host,
                source_port,
                err,
            )
            return

        if dispatch is None:
            _LOGGER.debug(
                "Ignoring syslog datagram from unconfigured host %s", source_host
            )
            return

        self._hass.async_create_task(
            self._async_dispatch(dispatch),
        )

    async def _async_dispatch(self, dispatch: SyslogDispatch) -> None:
        """Dispatch a routed syslog event and contain handler failures."""
        try:
            await dispatch.coordinator.async_handle_syslog_event(dispatch.event)
        except Exception:
            _LOGGER.debug(
                "Failed to handle syslog event from %s",
                dispatch.event.source_host,
                exc_info=True,
            )


class _SyslogUDPProtocol(asyncio.DatagramProtocol):
    """Asyncio UDP protocol for syslog datagrams."""

    def __init__(self, on_datagram: Callable[[bytes, str, int], None]) -> None:
        """Initialize the protocol."""
        self._on_datagram = on_datagram

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle an incoming UDP datagram."""
        source_host, source_port = addr[:2]
        self._on_datagram(data, source_host, source_port)


def parse_syslog_message(raw: bytes | str) -> SyslogEvent:
    """Parse an NMC syslog message."""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = text.strip()
    if match := RFC5424_HEADER_RE.match(text):
        return _parse_rfc5424_match(match)
    if match := RFC3164_RE.match(text):
        return _parse_rfc3164_match(match)

    raise SyslogParseError("Unsupported syslog message format")


def _syslog_datagram_log_text(raw: bytes) -> str:
    """Return a syslog datagram as single-line text for explicit capture logging."""
    text = raw.decode("utf-8", errors="backslashreplace")
    return text.replace("\r", r"\r").replace("\n", r"\n")


def _parse_rfc5424_match(match: re.Match[str]) -> SyslogEvent:
    """Return a syslog event from an RFC5424-style regex match."""
    priority = int(match.group("priority"))
    try:
        timestamp = datetime.fromisoformat(match.group("timestamp"))
    except ValueError as err:
        raise SyslogParseError("Invalid RFC5424 syslog timestamp") from err
    structured_data, structured_data_elements, message = _parse_structured_data(
        match.group("remainder") or ""
    )

    return SyslogEvent(
        priority=priority,
        facility=FACILITY.get(priority // 8, "unknown"),
        severity=SEVERITY.get(priority % 8, "unknown"),
        timestamp=timestamp,
        hostname=match.group("hostname"),
        app_name=match.group("app_name"),
        proc_id=match.group("proc_id"),
        msg_id=match.group("msg_id"),
        structured_data=structured_data,
        message=message,
        event_category=_event_category(match.group("proc_id"), match.group("msg_id")),
        event_text=message,
        structured_data_elements=structured_data_elements,
    )


def _parse_structured_data(
    remainder: str,
) -> tuple[str, tuple[SyslogStructuredDataElement, ...], str]:
    """Split RFC5424 structured data from the message body."""
    if not remainder:
        return "-", (), ""

    if remainder == "-":
        return "-", (), ""
    if remainder.startswith("- "):
        return "-", (), remainder[2:]
    if not remainder.startswith("["):
        return "-", (), remainder

    structured_end = _structured_data_end(remainder)
    if structured_end is None:
        raise SyslogParseError("Invalid RFC5424 structured data")

    structured_data = remainder[:structured_end]
    if structured_end == len(remainder):
        message = ""
    elif remainder[structured_end] == " ":
        message = remainder[structured_end + 1 :]
    else:
        raise SyslogParseError("Invalid RFC5424 structured data")

    return structured_data, _structured_data_elements(structured_data), message


def _structured_data_end(text: str) -> int | None:
    """Return the exclusive end index for one RFC5424 structured data value."""
    if not text.startswith("["):
        return None

    index = 0
    while index < len(text) and text[index] == "[":
        element_end = _structured_data_element_end(text, index)
        if element_end is None:
            return None
        index = element_end

    return index


def _structured_data_element_end(text: str, start: int) -> int | None:
    """Return the exclusive end index for the SD-ELEMENT opening at ``start``.

    A structured data value may hold several adjacent ``[...]`` elements, so
    element iteration needs the end of exactly one element. The closing ``]``
    only counts outside quoted parameter values and when not escaped.
    """
    index = start + 1
    in_quote = False
    escaped = False
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_quote = not in_quote
        elif char == "]" and not in_quote:
            return index + 1
        index += 1

    return None


def _structured_data_elements(
    structured_data: str,
) -> tuple[SyslogStructuredDataElement, ...]:
    """Parse RFC5424 structured data elements."""
    elements: list[SyslogStructuredDataElement] = []
    index = 0
    while index < len(structured_data):
        if structured_data[index] != "[":
            raise SyslogParseError("Invalid RFC5424 structured data")

        element_end = _structured_data_element_end(structured_data, index)
        if element_end is None:
            raise SyslogParseError("Invalid RFC5424 structured data")

        element_text = structured_data[index + 1 : element_end - 1]
        elements.append(_structured_data_element(element_text))
        index = element_end

    return tuple(elements)


def _structured_data_element(element_text: str) -> SyslogStructuredDataElement:
    """Parse one RFC5424 structured data element."""
    if not element_text:
        raise SyslogParseError("Invalid RFC5424 structured data")

    if " " in element_text:
        element_id, parameters_text = element_text.split(" ", 1)
    else:
        element_id = element_text
        parameters_text = ""

    return SyslogStructuredDataElement(
        element_id=element_id,
        parameters=_structured_data_parameters(parameters_text),
    )


def _structured_data_parameters(parameters_text: str) -> dict[str, str]:
    """Parse RFC5424 structured data parameters."""
    parameters: dict[str, str] = {}
    index = 0
    while index < len(parameters_text):
        while index < len(parameters_text) and parameters_text[index] == " ":
            index += 1
        if index == len(parameters_text):
            break

        name_start = index
        while index < len(parameters_text) and parameters_text[index] != "=":
            index += 1
        if index == name_start or index == len(parameters_text):
            raise SyslogParseError("Invalid RFC5424 structured data parameter")
        name = parameters_text[name_start:index]

        index += 1
        if index == len(parameters_text) or parameters_text[index] != '"':
            raise SyslogParseError("Invalid RFC5424 structured data parameter")
        index += 1

        value, index = _quoted_parameter_value(parameters_text, index)
        parameters[name] = value

        if index < len(parameters_text) and parameters_text[index] != " ":
            raise SyslogParseError("Invalid RFC5424 structured data parameter")

    return parameters


def _quoted_parameter_value(text: str, index: int) -> tuple[str, int]:
    """Return one quoted RFC5424 structured data parameter value."""
    value: list[str] = []
    escaped = False
    while index < len(text):
        char = text[index]
        if escaped:
            value.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return "".join(value), index + 1
        else:
            value.append(char)
        index += 1

    raise SyslogParseError("Invalid RFC5424 structured data parameter")


def _parse_rfc3164_match(match: re.Match[str]) -> SyslogEvent:
    """Return a syslog event from an RFC3164-style regex match."""
    priority = int(match.group("priority"))
    timestamp = _parse_rfc3164_timestamp(match.group("timestamp"))
    message = match.group("message")

    return SyslogEvent(
        priority=priority,
        facility=FACILITY.get(priority // 8, "unknown"),
        severity=SEVERITY.get(priority % 8, "unknown"),
        timestamp=timestamp,
        hostname=match.group("hostname"),
        app_name="-",
        proc_id="-",
        msg_id="-",
        structured_data="-",
        message=message,
        event_category=None,
        event_text=message,
    )


def _parse_rfc3164_timestamp(timestamp: str) -> datetime:
    """Parse an RFC3164 timestamp using the current year and UTC."""
    try:
        parsed = datetime.strptime(
            f"{datetime.now().year} {timestamp}",
            "%Y %b %d %H:%M:%S",
        )
    except ValueError as err:
        raise SyslogParseError("Invalid RFC3164 syslog timestamp") from err

    return parsed.replace(tzinfo=UTC)


def route_syslog_datagram(
    raw: bytes,
    *,
    source_host: str,
    source_port: int,
    coordinators_by_host: Mapping[str, SyslogEventCoordinator],
) -> SyslogDispatch | None:
    """Parse and route a syslog datagram to a configured coordinator."""
    coordinator = syslog_coordinator_for_source(source_host, coordinators_by_host)
    if coordinator is None:
        return None

    return SyslogDispatch(
        coordinator=coordinator,
        event=RoutedSyslogEvent(
            source_host=source_host,
            source_port=source_port,
            event=parse_syslog_message(raw),
        ),
    )


def syslog_coordinator_for_source(
    source_host: str,
    coordinators_by_host: Mapping[str, SyslogEventCoordinator],
) -> SyslogEventCoordinator | None:
    """Return the coordinator registered for a syslog packet source."""
    return coordinators_by_host.get(syslog_route_key(source_host))


def syslog_route_keys(host: str) -> set[str]:
    """Return all route keys that should match one syslog host string."""
    route_key = syslog_route_key(host)
    route_keys = {host, route_key}
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return route_keys

    if isinstance(address, ipaddress.IPv4Address):
        route_keys.add(f"::ffff:{address}")

    return route_keys


def syslog_route_key(host: str) -> str:
    """Return the canonical route key for a syslog packet source."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)

    return str(address)


def syslog_event_state_data(event: RoutedSyslogEvent) -> dict[str, Any]:
    """Return Home Assistant event state data for a routed syslog event."""
    syslog_event = event.event
    state_data: dict[str, Any] = {
        "source_host": event.source_host,
        "source_port": event.source_port,
        "priority": syslog_event.priority,
        "facility": syslog_event.facility,
        "severity": syslog_event.severity,
        "hostname": syslog_event.hostname,
        "app_name": syslog_event.app_name,
        "proc_id": syslog_event.proc_id,
        "msg_id": syslog_event.msg_id,
        "timestamp": syslog_event.timestamp.isoformat(),
        "message": syslog_event.event_text,
    }
    if syslog_event.event_category is not None:
        state_data["category"] = syslog_event.event_category
    if syslog_event.structured_data != "-":
        state_data["structured_data"] = syslog_event.structured_data
    if syslog_event.structured_data_elements:
        state_data["structured_data_elements"] = [
            {
                "id": element.element_id,
                "parameters": dict(element.parameters),
            }
            for element in syslog_event.structured_data_elements
        ]

    return state_data


def _event_category(proc_id: str, msg_id: str) -> str | None:
    """Build an event category from RFC5424 proc and message identifiers."""
    parts = [part for part in (proc_id, msg_id) if part != "-"]
    if not parts:
        return None

    return " ".join(parts)
