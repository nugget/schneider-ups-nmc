"""SNMP client and data normalization for APC UPS NMC."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SNMP_VERSION_2C = "2c"
SNMP_VERSION_3 = "3"

AUTH_PROTOCOL_NONE = "none"
AUTH_PROTOCOL_MD5 = "md5"
AUTH_PROTOCOL_SHA = "sha"

PRIVACY_PROTOCOL_NONE = "none"
PRIVACY_PROTOCOL_DES = "des"
PRIVACY_PROTOCOL_AES = "aes"

NO_SUCH_PREFIXES = (
    "No Such Object",
    "No Such Instance",
    "No more variables left",
)
DATE_FORMATS = (
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%Y-%m-%d",
    "%Y/%m/%d",
)

_LOGGER = logging.getLogger(__name__)


class SNMPError(Exception):
    """Raised when an SNMP query fails."""


class SNMPConfigurationError(SNMPError):
    """Raised when local SNMP connection settings are invalid."""


@dataclass(frozen=True)
class SNMPConnectionConfig:
    """SNMP connection settings."""

    host: str
    port: int = 161
    version: str = SNMP_VERSION_2C
    community: str | None = None
    username: str | None = None
    auth_protocol: str = AUTH_PROTOCOL_NONE
    auth_key: str | None = None
    privacy_protocol: str = PRIVACY_PROTOCOL_NONE
    privacy_key: str | None = None
    timeout: float = 2.0
    retries: int = 1


@dataclass(frozen=True)
class EnvironmentalProbe:
    """Normalized NMC environmental probe telemetry."""

    index: str
    name: str | None
    location: str | None
    connected: bool
    temperature: int | None
    humidity: int | None


@dataclass(frozen=True)
class UPSData:
    """Normalized UPS telemetry and identity."""

    values: Mapping[str, Any]
    name: str
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    firmware_version: str | None
    agent_version: str | None
    mac_address: str | None
    unique_id: str
    environmental_probes: tuple[EnvironmentalProbe, ...] = ()

    def value(self, key: str, default: Any = None) -> Any:
        """Return a normalized value by key."""
        return self.values.get(key, default)


RFC1628_OIDS: dict[str, str] = {
    "sys_description": "1.3.6.1.2.1.1.1.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
    "manufacturer": "1.3.6.1.2.1.33.1.1.1.0",
    "model": "1.3.6.1.2.1.33.1.1.2.0",
    "firmware_version": "1.3.6.1.2.1.33.1.1.3.0",
    "agent_version": "1.3.6.1.2.1.33.1.1.4.0",
    "ups_name": "1.3.6.1.2.1.33.1.1.5.0",
    "attached_devices": "1.3.6.1.2.1.33.1.1.6.0",
    "battery_status_code": "1.3.6.1.2.1.33.1.2.1.0",
    "seconds_on_battery": "1.3.6.1.2.1.33.1.2.2.0",
    "estimated_runtime_minutes": "1.3.6.1.2.1.33.1.2.3.0",
    "battery_charge": "1.3.6.1.2.1.33.1.2.4.0",
    "battery_voltage_tenths": "1.3.6.1.2.1.33.1.2.5.0",
    "battery_current_tenths": "1.3.6.1.2.1.33.1.2.6.0",
    "battery_temperature": "1.3.6.1.2.1.33.1.2.7.0",
    "input_line_bads": "1.3.6.1.2.1.33.1.3.1.0",
    "input_frequency_tenths": "1.3.6.1.2.1.33.1.3.3.1.2.1",
    "input_voltage": "1.3.6.1.2.1.33.1.3.3.1.3.1",
    "input_current_tenths": "1.3.6.1.2.1.33.1.3.3.1.4.1",
    "input_power": "1.3.6.1.2.1.33.1.3.3.1.5.1",
    "output_source_code": "1.3.6.1.2.1.33.1.4.1.0",
    "output_frequency_tenths": "1.3.6.1.2.1.33.1.4.2.0",
    "output_voltage": "1.3.6.1.2.1.33.1.4.4.1.2.1",
    "output_current_tenths": "1.3.6.1.2.1.33.1.4.4.1.3.1",
    "output_power": "1.3.6.1.2.1.33.1.4.4.1.4.1",
    "output_load": "1.3.6.1.2.1.33.1.4.4.1.5.1",
    "alarm_count": "1.3.6.1.2.1.33.1.6.1.0",
}

POWERNET_OIDS: dict[str, str] = {
    "apc_model": "1.3.6.1.4.1.318.1.1.1.1.1.1.0",
    "apc_ups_name": "1.3.6.1.4.1.318.1.1.1.1.1.2.0",
    "apc_firmware_version": "1.3.6.1.4.1.318.1.1.1.1.2.1.0",
    "apc_manufacture_date": "1.3.6.1.4.1.318.1.1.1.1.2.2.0",
    "apc_serial_number": "1.3.6.1.4.1.318.1.1.1.1.2.3.0",
    "apc_sku": "1.3.6.1.4.1.318.1.1.1.1.2.5.0",
    "powernet_battery_status_code": "1.3.6.1.4.1.318.1.1.1.2.1.1.0",
    "battery_last_replace_date_raw": "1.3.6.1.4.1.318.1.1.1.2.1.3.0",
    "powernet_battery_charge_tenths": "1.3.6.1.4.1.318.1.1.1.2.3.1.0",
    "powernet_battery_temperature_tenths": "1.3.6.1.4.1.318.1.1.1.2.3.2.0",
    "powernet_battery_voltage_tenths": "1.3.6.1.4.1.318.1.1.1.2.3.4.0",
    "battery_replace_indicator_code": "1.3.6.1.4.1.318.1.1.1.2.2.4.0",
    "battery_pack_count": "1.3.6.1.4.1.318.1.1.1.2.2.5.0",
    "battery_internal_sku": "1.3.6.1.4.1.318.1.1.1.2.2.19.0",
    "battery_external_sku": "1.3.6.1.4.1.318.1.1.1.2.2.20.0",
    "battery_recommended_replace_date_raw": "1.3.6.1.4.1.318.1.1.1.2.2.21.0",
    "powernet_input_voltage_tenths": "1.3.6.1.4.1.318.1.1.1.3.3.1.0",
    "powernet_input_max_voltage_tenths": "1.3.6.1.4.1.318.1.1.1.3.3.2.0",
    "powernet_input_min_voltage_tenths": "1.3.6.1.4.1.318.1.1.1.3.3.3.0",
    "powernet_input_frequency_tenths": "1.3.6.1.4.1.318.1.1.1.3.3.4.0",
    "input_line_fail_cause_code": "1.3.6.1.4.1.318.1.1.1.3.2.5.0",
    "ups_status_code": "1.3.6.1.4.1.318.1.1.1.4.1.1.0",
    "powernet_output_voltage_tenths": "1.3.6.1.4.1.318.1.1.1.4.3.1.0",
    "powernet_output_frequency_tenths": "1.3.6.1.4.1.318.1.1.1.4.3.2.0",
    "powernet_output_load_tenths": "1.3.6.1.4.1.318.1.1.1.4.3.3.0",
    "powernet_output_current_tenths": "1.3.6.1.4.1.318.1.1.1.4.3.4.0",
    "powernet_output_active_power": "1.3.6.1.4.1.318.1.1.1.4.2.8.0",
    "powernet_output_apparent_power": "1.3.6.1.4.1.318.1.1.1.4.2.9.0",
    "output_efficiency_tenths": "1.3.6.1.4.1.318.1.1.1.4.3.5.0",
    "output_energy_hundredths_kwh": "1.3.6.1.4.1.318.1.1.1.4.3.6.0",
    "self_test_result_code": "1.3.6.1.4.1.318.1.1.1.7.2.3.0",
    "self_test_last_date_raw": "1.3.6.1.4.1.318.1.1.1.7.2.4.0",
}

OIDS: dict[str, str] = {**RFC1628_OIDS, **POWERNET_OIDS}

GET_BATCH_SIZE = 12
# AP9335T/AP9335TH probes are exposed through the PowerNet Universal
# Input/Output sensor status table.
UIO_SENSOR_STATUS_NAME_OID = "1.3.6.1.4.1.318.1.1.25.1.2.1.3"
UIO_SENSOR_STATUS_LOCATION_OID = "1.3.6.1.4.1.318.1.1.25.1.2.1.4"
UIO_SENSOR_STATUS_TEMPERATURE_C_OID = "1.3.6.1.4.1.318.1.1.25.1.2.1.6"
UIO_SENSOR_STATUS_HUMIDITY_OID = "1.3.6.1.4.1.318.1.1.25.1.2.1.7"
UIO_SENSOR_STATUS_COMM_STATUS_OID = "1.3.6.1.4.1.318.1.1.25.1.2.1.10"
UIO_SENSOR_COMM_STATUS_OK = 2
IF_TYPE_OID = "1.3.6.1.2.1.2.2.1.3"
IF_PHYS_ADDRESS_OID = "1.3.6.1.2.1.2.2.1.6"
ETHERNET_CSMACD_IF_TYPE = 6
MAX_TABLE_ROWS = 64
MAC_ADDRESS_OCTETS = 6
VAR_BIND_PARTS = 2
MAC_PAIR_RE = re.compile(r"[0-9A-Fa-f]{2}")

BATTERY_STATUS_OPTIONS = [
    "unknown",
    "normal",
    "low",
    "depleted",
    "fault",
    "no_battery_present",
]
BATTERY_STATUS = {
    1: "unknown",
    2: "normal",
    3: "low",
    4: "depleted",
}

POWERNET_BATTERY_STATUS = {
    1: "unknown",
    2: "normal",
    3: "low",
    4: "fault",
    5: "no_battery_present",
}

BATTERY_REPLACE_INDICATOR_OPTIONS = [
    "ok",
    "needs_replacement",
]
BATTERY_REPLACE_INDICATOR = {
    1: "ok",
    2: "needs_replacement",
}

OUTPUT_SOURCE_OPTIONS = [
    "other",
    "none",
    "normal",
    "bypass",
    "battery",
    "booster",
    "reducer",
]
OUTPUT_SOURCE = {
    1: "other",
    2: "none",
    3: "normal",
    4: "bypass",
    5: "battery",
    6: "booster",
    7: "reducer",
}

UPS_STATUS_OPTIONS = [
    "unknown",
    "online",
    "on_battery",
    "smart_boost",
    "timed_sleeping",
    "software_bypass",
    "off",
    "rebooting",
    "switched_bypass",
    "hardware_failure_bypass",
    "sleeping_until_power_return",
    "smart_trim",
    "eco_mode",
    "hot_standby",
    "on_battery_test",
    "emergency_static_bypass",
    "static_bypass_standby",
    "power_saving_mode",
    "spot_mode",
    "e_conversion",
    "charger_spot_mode",
    "inverter_spot_mode",
    "active_load",
    "battery_discharge_spot_mode",
    "inverter_standby",
    "charger_only",
    "distributed_energy_reserve",
    "self_test",
]
UPS_STATUS = {
    1: "unknown",
    2: "online",
    3: "on_battery",
    4: "smart_boost",
    5: "timed_sleeping",
    6: "software_bypass",
    7: "off",
    8: "rebooting",
    9: "switched_bypass",
    10: "hardware_failure_bypass",
    11: "sleeping_until_power_return",
    12: "smart_trim",
    13: "eco_mode",
    14: "hot_standby",
    15: "on_battery_test",
    16: "emergency_static_bypass",
    17: "static_bypass_standby",
    18: "power_saving_mode",
    19: "spot_mode",
    20: "e_conversion",
    21: "charger_spot_mode",
    22: "inverter_spot_mode",
    23: "active_load",
    24: "battery_discharge_spot_mode",
    25: "inverter_standby",
    26: "charger_only",
    27: "distributed_energy_reserve",
    28: "self_test",
}

INPUT_LINE_FAIL_CAUSE_OPTIONS = [
    "no_transfer",
    "high_line_voltage",
    "brownout",
    "blackout",
    "small_momentary_sag",
    "deep_momentary_sag",
    "small_momentary_spike",
    "large_momentary_spike",
    "self_test",
    "rate_of_voltage_change",
]
INPUT_LINE_FAIL_CAUSE = {
    1: "no_transfer",
    2: "high_line_voltage",
    3: "brownout",
    4: "blackout",
    5: "small_momentary_sag",
    6: "deep_momentary_sag",
    7: "small_momentary_spike",
    8: "large_momentary_spike",
    9: "self_test",
    10: "rate_of_voltage_change",
}

SELF_TEST_RESULT_OPTIONS = [
    "ok",
    "failed",
    "invalid_test",
    "test_in_progress",
]
SELF_TEST_RESULT = {
    1: "ok",
    2: "failed",
    3: "invalid_test",
    4: "test_in_progress",
}


class SNMPClient:
    """Minimal async SNMP client for UPS telemetry."""

    def __init__(self, config: SNMPConnectionConfig) -> None:
        """Initialize the client."""
        self.config = config
        self._closed = False
        self._engine_lock: asyncio.Lock | None = None
        self._mac_address: str | None = None
        self._snmp_engine: Any | None = None

    async def async_get_data(self) -> UPSData:
        """Fetch and normalize UPS data."""
        raw_by_oid = await self.async_get(tuple(OIDS.values()))
        raw_by_key = {key: raw_by_oid.get(oid) for key, oid in OIDS.items()}
        try:
            raw_by_key["mac_address"] = await self.async_get_mac_address()
        except SNMPError:
            raw_by_key["mac_address"] = None
        try:
            raw_by_key[
                "environmental_probes"
            ] = await self.async_get_environmental_probes()
        except SNMPError as err:
            _LOGGER.debug("Could not query APC UPS NMC environmental probes: %s", err)
            raw_by_key["environmental_probes"] = ()

        return build_ups_data(
            raw_by_key,
            fallback_name=self.config.host,
            fallback_unique_id=f"{self.config.host}:{self.config.port}",
        )

    async def async_get_mac_address(self) -> str | None:
        """Fetch the management card MAC address from IF-MIB."""
        self._raise_if_closed()
        if self._mac_address is not None:
            return self._mac_address

        interface_types = await self._async_walk_column(IF_TYPE_OID)
        self._raise_if_closed()
        physical_addresses = await self._async_walk_column(IF_PHYS_ADDRESS_OID)
        self._raise_if_closed()
        mac_address = _select_interface_mac_address(
            interface_types,
            physical_addresses,
        )
        if mac_address is not None:
            self._mac_address = mac_address
        return mac_address

    async def async_get_environmental_probes(
        self,
    ) -> tuple[EnvironmentalProbe, ...]:
        """Fetch NMC universal I/O environmental probe readings."""
        self._raise_if_closed()
        names = await self._async_walk_column_values(UIO_SENSOR_STATUS_NAME_OID)
        self._raise_if_closed()
        locations = await self._async_walk_column_values(UIO_SENSOR_STATUS_LOCATION_OID)
        self._raise_if_closed()
        temperatures = await self._async_walk_column_values(
            UIO_SENSOR_STATUS_TEMPERATURE_C_OID
        )
        self._raise_if_closed()
        humidity = await self._async_walk_column_values(UIO_SENSOR_STATUS_HUMIDITY_OID)
        self._raise_if_closed()
        comm_status = await self._async_walk_column_values(
            UIO_SENSOR_STATUS_COMM_STATUS_OID
        )

        return _build_uio_environmental_probes(
            names,
            locations,
            temperatures,
            humidity,
            comm_status,
        )

    async def async_get(self, oids: Sequence[str]) -> dict[str, Any]:
        """Fetch OIDs from the configured SNMP agent."""
        values: dict[str, Any] = {}
        for oid_batch in _chunks(oids, GET_BATCH_SIZE):
            values.update(await self._async_get_batch(oid_batch))

        return values

    async def _async_get_batch(self, oids: Sequence[str]) -> dict[str, Any]:
        """Fetch one bounded batch of OIDs from the configured SNMP agent."""
        from pysnmp.hlapi.v3arch.asyncio import (  # pylint: disable=import-outside-toplevel
            ContextData,
            ObjectIdentity,
            ObjectType,
            get_cmd,
        )

        auth_data = self._auth_data()
        var_binds = [ObjectType(ObjectIdentity(oid)) for oid in oids]

        try:
            error_indication, error_status, error_index, result_binds = await get_cmd(
                await self._async_engine(),
                auth_data,
                await self._async_transport_target(),
                ContextData(),
                *var_binds,
                lookupMib=False,
            )
        except Exception as err:
            raise SNMPError(str(err)) from err

        if error_indication:
            raise SNMPError(str(error_indication))

        if error_status:
            failed_oid = "unknown"
            if error_index:
                failed_index = int(error_index) - 1
                if 0 <= failed_index < len(oids):
                    failed_oid = oids[failed_index]
            pretty_print = getattr(error_status, "prettyPrint", None)
            error_text = pretty_print() if callable(pretty_print) else str(error_status)
            raise SNMPError(f"{error_text} at {failed_oid}")

        values: dict[str, Any] = {}
        if len(result_binds) != len(oids):
            raise SNMPError(
                f"SNMP response returned {len(result_binds)} values for "
                f"{len(oids)} requested OIDs"
            )

        for oid, result in zip(oids, result_binds, strict=True):
            values[oid] = _coerce_snmp_value(result[1])

        return values

    async def _async_walk_column(self, column_oid: str) -> dict[str, Any]:
        """Walk one SNMP table column and return values keyed by row index."""
        from pysnmp.hlapi.v3arch.asyncio import (  # pylint: disable=import-outside-toplevel
            ContextData,
            ObjectIdentity,
            ObjectType,
            next_cmd,
        )

        auth_data = self._auth_data()
        transport_target = await self._async_transport_target()
        current_oid = column_oid
        values: dict[str, Any] = {}

        for _ in range(MAX_TABLE_ROWS):
            try:
                (
                    error_indication,
                    error_status,
                    error_index,
                    result_binds,
                ) = await next_cmd(
                    await self._async_engine(),
                    auth_data,
                    transport_target,
                    ContextData(),
                    ObjectType(ObjectIdentity(current_oid)),
                    lookupMib=False,
                )
            except Exception as err:
                raise SNMPError(str(err)) from err

            if error_indication:
                raise SNMPError(str(error_indication))

            if error_status:
                pretty_print = getattr(error_status, "prettyPrint", None)
                error_text = (
                    pretty_print() if callable(pretty_print) else str(error_status)
                )
                raise SNMPError(f"{error_text} at row {error_index}")

            if not result_binds:
                break

            result = _first_result_bind(result_binds)
            if result is None:
                break

            result_oid = str(result[0])
            row_index = _row_index(column_oid, result_oid)
            if row_index is None:
                break

            values[row_index] = result[1]
            current_oid = result_oid

        return values

    async def _async_walk_column_values(self, column_oid: str) -> dict[str, Any]:
        """Walk one SNMP table column and coerce values to simple types."""
        raw_values = await self._async_walk_column(column_oid)
        return {
            row_index: _coerce_snmp_value(value)
            for row_index, value in raw_values.items()
        }

    def _raise_if_closed(self) -> None:
        """Raise when a lifecycle owner uses the client after teardown."""
        if self._closed:
            raise SNMPError("SNMP client is closed")

    async def _async_transport_target(self) -> Any:
        """Create a PySNMP UDP target for one SNMP operation."""
        from pysnmp.hlapi.v3arch.asyncio import (  # pylint: disable=import-outside-toplevel
            UdpTransportTarget,
        )

        # Target creation resolves hostnames. PySNMP's command-generator LCD
        # caches the actual UDP transport on the SNMP engine, so avoid retaining
        # a resolved target across refreshes while still reusing the socket.
        return await UdpTransportTarget.create(
            (self.config.host, self.config.port),
            timeout=self.config.timeout,
            retries=self.config.retries,
        )

    def close(self) -> None:
        """Close the underlying SNMP dispatcher."""
        self._closed = True
        self._mac_address = None
        snmp_engine = self._snmp_engine
        self._snmp_engine = None

        if snmp_engine is None:
            return

        _close_snmp_engine(snmp_engine)

    async def _async_engine(self) -> Any:
        """Return a lazily-created SNMP engine."""
        if self._snmp_engine is not None:
            return self._snmp_engine

        if self._closed:
            raise SNMPError("SNMP client is closed")

        if self._engine_lock is None:
            self._engine_lock = asyncio.Lock()

        async with self._engine_lock:
            if self._snmp_engine is not None:
                return self._snmp_engine

            if self._closed:
                raise SNMPError("SNMP client is closed")

            snmp_engine = await asyncio.to_thread(self._create_snmp_engine)
            if self._closed:
                _close_snmp_engine(snmp_engine)
                raise SNMPError("SNMP client is closed")

            self._snmp_engine = snmp_engine

        return self._snmp_engine

    def _create_snmp_engine(self) -> Any:
        """Create the PySNMP engine outside the event loop."""
        from pysnmp.hlapi.v3arch.asyncio import (  # pylint: disable=import-outside-toplevel
            SnmpEngine,
        )

        return SnmpEngine()

    def _auth_data(self) -> Any:
        """Build PySNMP authentication data."""
        from pysnmp.hlapi.v3arch.asyncio import (  # pylint: disable=import-outside-toplevel
            CommunityData,
            UsmUserData,
            usmAesCfb128Protocol,
            usmDESPrivProtocol,
            usmHMACMD5AuthProtocol,
            usmHMACSHAAuthProtocol,
            usmNoAuthProtocol,
            usmNoPrivProtocol,
        )

        if self.config.version == SNMP_VERSION_2C:
            if not self.config.community:
                raise SNMPConfigurationError("SNMPv2c community is required")
            return CommunityData(self.config.community, mpModel=1)

        if self.config.version != SNMP_VERSION_3:
            raise SNMPConfigurationError(
                f"Unsupported SNMP version: {self.config.version}"
            )

        if not self.config.username:
            raise SNMPConfigurationError("SNMPv3 requires a username")

        auth_protocols = {
            AUTH_PROTOCOL_NONE: usmNoAuthProtocol,
            AUTH_PROTOCOL_MD5: usmHMACMD5AuthProtocol,
            AUTH_PROTOCOL_SHA: usmHMACSHAAuthProtocol,
        }
        privacy_protocols = {
            PRIVACY_PROTOCOL_NONE: usmNoPrivProtocol,
            PRIVACY_PROTOCOL_DES: usmDESPrivProtocol,
            PRIVACY_PROTOCOL_AES: usmAesCfb128Protocol,
        }

        auth_protocol = auth_protocols.get(self.config.auth_protocol)
        privacy_protocol = privacy_protocols.get(self.config.privacy_protocol)

        if auth_protocol is None:
            raise SNMPConfigurationError(
                f"Unsupported SNMPv3 auth protocol: {self.config.auth_protocol}"
            )
        if privacy_protocol is None:
            raise SNMPConfigurationError(
                f"Unsupported SNMPv3 privacy protocol: {self.config.privacy_protocol}"
            )
        if self.config.auth_protocol != AUTH_PROTOCOL_NONE and not self.config.auth_key:
            raise SNMPConfigurationError("SNMPv3 authentication passphrase is required")
        if (
            self.config.privacy_protocol != PRIVACY_PROTOCOL_NONE
            and not self.config.privacy_key
        ):
            raise SNMPConfigurationError("SNMPv3 privacy passphrase is required")
        if (
            self.config.privacy_protocol != PRIVACY_PROTOCOL_NONE
            and self.config.auth_protocol == AUTH_PROTOCOL_NONE
        ):
            raise SNMPConfigurationError("SNMPv3 privacy requires authentication")

        return UsmUserData(
            self.config.username,
            self.config.auth_key,
            self.config.privacy_key,
            authProtocol=auth_protocol,
            privProtocol=privacy_protocol,
        )


def _close_snmp_engine(snmp_engine: Any) -> None:
    """Close a PySNMP engine dispatcher."""
    close_dispatcher = getattr(snmp_engine, "close_dispatcher", None)
    if callable(close_dispatcher):
        close_dispatcher()

    transport_dispatcher = _transport_dispatcher(snmp_engine)
    if transport_dispatcher is not None:
        close_dispatcher = getattr(
            transport_dispatcher,
            "close_dispatcher",
            None,
        )
        if not callable(close_dispatcher):
            close_dispatcher = getattr(
                transport_dispatcher,
                "closeDispatcher",
                None,
            )
        if callable(close_dispatcher):
            close_dispatcher()


def _transport_dispatcher(snmp_engine: Any) -> Any | None:
    """Return the PySNMP transport dispatcher without global warning filters."""
    try:
        return snmp_engine.transport_dispatcher
    except AttributeError:
        return getattr(snmp_engine, "transportDispatcher", None)


def build_ups_data(
    raw: Mapping[str, Any],
    *,
    fallback_name: str = "UPS",
    fallback_unique_id: str | None = None,
) -> UPSData:
    """Normalize raw SNMP values into Home Assistant-friendly data."""
    values = dict(raw)
    values.pop("mac_address", None)
    values["battery_status"] = _enum_name(
        POWERNET_BATTERY_STATUS,
        raw.get("powernet_battery_status_code"),
    ) or _enum_name(BATTERY_STATUS, raw.get("battery_status_code"))
    values["estimated_runtime"] = _minutes_to_seconds(
        raw.get("estimated_runtime_minutes")
    )
    values["battery_charge"] = _first_present(
        _tenths(raw.get("powernet_battery_charge_tenths")),
        _int(raw.get("battery_charge")),
    )
    values["battery_voltage"] = _first_present(
        _tenths(raw.get("powernet_battery_voltage_tenths")),
        _tenths(raw.get("battery_voltage_tenths")),
    )
    values["battery_current"] = _tenths(raw.get("battery_current_tenths"))
    values["battery_temperature"] = _first_present(
        _tenths(raw.get("powernet_battery_temperature_tenths")),
        raw.get("battery_temperature"),
    )
    values["battery_replace_indicator"] = _enum_name(
        BATTERY_REPLACE_INDICATOR,
        raw.get("battery_replace_indicator_code"),
    )
    values["battery_last_replace_date"] = _date(
        raw.get("battery_last_replace_date_raw")
    )
    values["battery_recommended_replace_date"] = _date(
        raw.get("battery_recommended_replace_date_raw")
    )
    values["input_voltage"] = _first_present(
        _tenths(raw.get("powernet_input_voltage_tenths")),
        raw.get("input_voltage"),
    )
    values["input_frequency"] = _first_present(
        _tenths(raw.get("powernet_input_frequency_tenths")),
        _tenths(raw.get("input_frequency_tenths")),
    )
    values["input_current"] = _tenths(raw.get("input_current_tenths"))
    values["input_line_fail_cause"] = _enum_name(
        INPUT_LINE_FAIL_CAUSE,
        raw.get("input_line_fail_cause_code"),
    )
    values["ups_status"] = _enum_name(UPS_STATUS, raw.get("ups_status_code"))
    values["output_source"] = _enum_name(
        OUTPUT_SOURCE,
        raw.get("output_source_code"),
    )
    values["output_voltage"] = _first_present(
        _tenths(raw.get("powernet_output_voltage_tenths")),
        raw.get("output_voltage"),
    )
    values["output_frequency"] = _first_present(
        _tenths(raw.get("powernet_output_frequency_tenths")),
        _tenths(raw.get("output_frequency_tenths")),
    )
    values["output_current"] = _first_present(
        _tenths(raw.get("powernet_output_current_tenths")),
        _tenths(raw.get("output_current_tenths")),
    )
    values["output_power"] = _first_present(
        raw.get("powernet_output_active_power"),
        raw.get("output_power"),
    )
    values["output_apparent_power"] = _first_present(
        raw.get("powernet_output_apparent_power")
    )
    values["output_power_factor"] = _power_factor(
        values["output_power"],
        values["output_apparent_power"],
    )
    values["output_load"] = _first_present(
        _tenths(raw.get("powernet_output_load_tenths")),
        raw.get("output_load"),
    )
    values["output_efficiency"] = _tenths(raw.get("output_efficiency_tenths"))
    values["output_energy"] = _hundredths(raw.get("output_energy_hundredths_kwh"))
    values["self_test_result"] = _enum_name(
        SELF_TEST_RESULT,
        raw.get("self_test_result_code"),
    )
    values["self_test_last_date"] = _date(raw.get("self_test_last_date_raw"))
    mac_address = _format_mac_address(raw.get("mac_address"))

    manufacturer = _first_text(raw, "manufacturer") or "Schneider Electric"
    model = _first_text(raw, "model", "apc_model")
    serial_number = _first_text(raw, "apc_serial_number")
    firmware_version = _first_text(raw, "firmware_version", "apc_firmware_version")
    agent_version = _first_text(raw, "agent_version")
    name = (
        _first_text(raw, "ups_name", "apc_ups_name", "sys_name", "model", "apc_model")
        or fallback_name
    )
    unique_id = (
        serial_number or _first_text(raw, "sys_name") or fallback_unique_id or name
    )

    return UPSData(
        values=values,
        name=name,
        manufacturer=manufacturer,
        model=model,
        serial_number=serial_number,
        firmware_version=firmware_version,
        agent_version=agent_version,
        mac_address=mac_address,
        unique_id=_slug(unique_id),
        environmental_probes=tuple(raw.get("environmental_probes") or ()),
    )


def _build_uio_environmental_probes(
    names: Mapping[str, Any],
    locations: Mapping[str, Any],
    temperatures: Mapping[str, Any],
    humidity: Mapping[str, Any],
    comm_status: Mapping[str, Any],
) -> tuple[EnvironmentalProbe, ...]:
    """Return normalized AP9335-style universal I/O environmental probes."""
    row_indexes = set(names) | set(locations) | set(temperatures) | set(humidity)
    row_indexes |= set(comm_status)
    probes: list[EnvironmentalProbe] = []

    for row_index in sorted(row_indexes, key=_row_sort_key):
        connected = _int(comm_status.get(row_index)) == UIO_SENSOR_COMM_STATUS_OK
        temperature = _environmental_reading(temperatures.get(row_index))
        relative_humidity = _environmental_reading(humidity.get(row_index))
        if not connected:
            temperature = None
            relative_humidity = None

        if (
            not connected
            and _text(names.get(row_index)) is None
            and _text(locations.get(row_index)) is None
            and temperature is None
            and relative_humidity is None
        ):
            continue

        probes.append(
            EnvironmentalProbe(
                index=row_index,
                name=_text(names.get(row_index)),
                location=_text(locations.get(row_index)),
                connected=connected,
                temperature=temperature,
                humidity=relative_humidity,
            )
        )

    return tuple(probes)


def _coerce_snmp_value(value: Any) -> int | str | None:
    """Convert a PySNMP value into a simple Python value."""
    pretty = value.prettyPrint() if hasattr(value, "prettyPrint") else str(value)
    pretty = pretty.strip()
    if not pretty or pretty.startswith(NO_SUCH_PREFIXES):
        return None

    try:
        return int(value)
    except TypeError, ValueError:
        return pretty


def _power_factor(
    active_power: Any,
    apparent_power: Any,
) -> float | None:
    """Return output power factor as a percentage from watts and volt-amperes."""
    active = _int(active_power)
    apparent = _int(apparent_power)
    if active is None or apparent is None or apparent <= 0:
        return None

    return round(max(0.0, min(100.0, active / apparent * 100)), 1)


def _select_interface_mac_address(
    interface_types: Mapping[str, Any],
    physical_addresses: Mapping[str, Any],
) -> str | None:
    """Return the best NMC MAC address from IF-MIB table values."""
    for row_index in sorted(physical_addresses, key=_row_sort_key):
        mac_address = _format_mac_address(physical_addresses[row_index])
        if mac_address is None:
            continue

        if _int(interface_types.get(row_index)) == ETHERNET_CSMACD_IF_TYPE:
            return mac_address

    return None


def _first_result_bind(result_binds: Sequence[Any]) -> Any | None:
    """Return the first SNMP result binding across PySNMP return shapes."""
    first_result = result_binds[0]
    if _looks_like_var_bind(first_result):
        return first_result
    if not isinstance(first_result, list | tuple):
        return first_result
    if not first_result:
        return None

    nested_result = first_result[0]
    if _looks_like_var_bind(nested_result):
        return nested_result

    return None


def _chunks(values: Sequence[str], size: int) -> list[Sequence[str]]:
    """Split values into stable bounded chunks."""
    return [values[index : index + size] for index in range(0, len(values), size)]


def _looks_like_var_bind(value: Any) -> bool:
    """Return whether a value resembles an SNMP `(oid, value)` binding."""
    return (
        not isinstance(value, str | bytes | bytearray)
        and isinstance(value, list | tuple)
        and len(value) == VAR_BIND_PARTS
    )


def _format_mac_address(value: Any) -> str | None:
    """Return a normalized MAC address from an SNMP physical address."""
    octets = _mac_octets(value)
    if octets is None or len(octets) != MAC_ADDRESS_OCTETS or not any(octets):
        return None

    return ":".join(f"{octet:02x}" for octet in octets)


def _mac_octets(value: Any) -> bytes | None:
    """Extract raw MAC octets from common SNMP value representations."""
    if value is None:
        return None

    octets: bytes | None = None
    as_octets = getattr(value, "asOctets", None)
    if callable(as_octets):
        raw_octets = as_octets()
        if isinstance(raw_octets, bytes | bytearray | list | tuple):
            octets = bytes(raw_octets)
    elif isinstance(value, bytes | bytearray):
        octets = bytes(value)
    else:
        text = str(value).strip()
        pairs = MAC_PAIR_RE.findall(text) if text else []
        if len(pairs) == MAC_ADDRESS_OCTETS:
            octets = bytes(int(pair, 16) for pair in pairs)

    return octets


def _row_index(column_oid: str, result_oid: str) -> str | None:
    """Return the table row index when a result belongs to the requested column."""
    prefix = f"{column_oid}."
    if not result_oid.startswith(prefix):
        return None

    return result_oid.removeprefix(prefix)


def _row_sort_key(row_index: str) -> tuple[int, ...]:
    """Return a numeric sort key for dotted SNMP table indexes."""
    return tuple(_int(part) or 0 for part in row_index.split("."))


def _first_text(raw: Mapping[str, Any], *keys: str) -> str | None:
    """Return the first non-empty text value from a mapping."""
    for key in keys:
        text = _text(raw.get(key))
        if text:
            return text

    return None


def _text(value: Any) -> str | None:
    """Return a stripped text value when the input is meaningful."""
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _enum_name(enum: Mapping[int, str], value: Any) -> str | None:
    """Return the normalized name for an integer enum value."""
    integer = _int(value)
    if integer is None:
        return None

    return enum.get(integer)


def _first_present(*values: Any) -> Any:
    """Return the first value that is not None."""
    for value in values:
        if value is not None:
            return value

    return None


def _int(value: Any) -> int | None:
    """Return a value as an integer, if possible."""
    if value is None:
        return None

    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _tenths(value: Any) -> float | None:
    """Convert a tenth-unit integer value to a float."""
    integer = _int(value)
    if integer is None:
        return None

    return integer / 10


def _environmental_reading(value: Any) -> int | None:
    """Return an environmental sensor reading when the NMC marks it valid."""
    integer = _int(value)
    if integer is None or integer < 0:
        return None

    return integer


def _hundredths(value: Any) -> float | None:
    """Convert a hundredth-unit integer value to a float."""
    integer = _int(value)
    if integer is None:
        return None

    return integer / 100


def _minutes_to_seconds(value: Any) -> int | None:
    """Convert minutes to seconds."""
    integer = _int(value)
    if integer is None:
        return None

    return integer * 60


def _date(value: Any) -> date | None:
    """Parse common NMC date strings."""
    text = _text(value)
    if text is None or text.lower() == "unknown":
        return None

    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue

    return None


def _slug(value: str) -> str:
    """Return a stable simple identifier."""
    slug = "".join(
        character.lower() if character.isalnum() else "_" for character in value
    )
    return "_".join(part for part in slug.split("_") if part)
