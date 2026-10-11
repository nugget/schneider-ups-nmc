"""Sensors for APC UPS NMC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import callback

from .entity import SchneiderUPSNMCEntity
from .snmp import (
    BATTERY_REPLACE_INDICATOR_OPTIONS,
    BATTERY_STATUS_OPTIONS,
    INPUT_LINE_FAIL_CAUSE_OPTIONS,
    OUTPUT_SOURCE_OPTIONS,
    SELF_TEST_RESULT_OPTIONS,
    UPS_STATUS_OPTIONS,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SchneiderUPSNMCConfigEntry
    from .coordinator import SchneiderUPSNMCCoordinator
    from .snmp import EnvironmentalProbe, UPSData


@dataclass(frozen=True, kw_only=True)
class SchneiderUPSNMCSensorEntityDescription(SensorEntityDescription):
    """Describe an APC UPS NMC sensor."""

    value_fn: Callable[[UPSData], Any]


def _value(key: str) -> Callable[[UPSData], Any]:
    """Return a value getter for a data key."""

    def get_value(data: UPSData) -> Any:
        return data.value(key)

    return get_value


SENSOR_DESCRIPTIONS: tuple[SchneiderUPSNMCSensorEntityDescription, ...] = (
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_status",
        translation_key="battery_status",
        device_class=SensorDeviceClass.ENUM,
        options=BATTERY_STATUS_OPTIONS,
        value_fn=_value("battery_status"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="ups_status",
        translation_key="ups_status",
        device_class=SensorDeviceClass.ENUM,
        options=UPS_STATUS_OPTIONS,
        value_fn=_value("ups_status"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_charge",
        translation_key="battery_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("battery_charge"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="estimated_runtime",
        translation_key="estimated_runtime",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("estimated_runtime"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="seconds_on_battery",
        translation_key="seconds_on_battery",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("seconds_on_battery"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("battery_voltage"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_current",
        translation_key="battery_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("battery_current"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_temperature",
        translation_key="battery_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("battery_temperature"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_replace_indicator",
        translation_key="battery_replace_indicator",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=BATTERY_REPLACE_INDICATOR_OPTIONS,
        value_fn=_value("battery_replace_indicator"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_pack_count",
        translation_key="battery_pack_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("battery_pack_count"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_internal_sku",
        translation_key="battery_internal_sku",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("battery_internal_sku"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_external_sku",
        translation_key="battery_external_sku",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("battery_external_sku"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_last_replace_date",
        translation_key="battery_last_replace_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("battery_last_replace_date"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="battery_recommended_replace_date",
        translation_key="battery_recommended_replace_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("battery_recommended_replace_date"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="input_voltage",
        translation_key="input_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("input_voltage"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="input_frequency",
        translation_key="input_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("input_frequency"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="input_current",
        translation_key="input_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("input_current"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="input_power",
        translation_key="input_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("input_power"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="input_line_fail_cause",
        translation_key="input_line_fail_cause",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        options=INPUT_LINE_FAIL_CAUSE_OPTIONS,
        value_fn=_value("input_line_fail_cause"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_source",
        translation_key="output_source",
        device_class=SensorDeviceClass.ENUM,
        options=OUTPUT_SOURCE_OPTIONS,
        value_fn=_value("output_source"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_voltage",
        translation_key="output_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_voltage"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_frequency",
        translation_key="output_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_frequency"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_current",
        translation_key="output_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_current"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_power",
        translation_key="output_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_power"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_apparent_power",
        translation_key="output_apparent_power",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_apparent_power"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_power_factor",
        translation_key="output_power_factor",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_power_factor"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_load",
        translation_key="output_load",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_load"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_efficiency",
        translation_key="output_efficiency",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_efficiency"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="output_energy",
        translation_key="output_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_value("output_energy"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="alarm_count",
        translation_key="alarm_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("alarm_count"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="input_line_bads",
        translation_key="input_line_bads",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_value("input_line_bads"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="self_test_result",
        translation_key="self_test_result",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=SELF_TEST_RESULT_OPTIONS,
        value_fn=_value("self_test_result"),
    ),
    SchneiderUPSNMCSensorEntityDescription(
        key="self_test_last_date",
        translation_key="self_test_last_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("self_test_last_date"),
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: SchneiderUPSNMCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up APC UPS NMC sensors."""
    coordinator: SchneiderUPSNMCCoordinator = entry.runtime_data
    environmental_entities: set[tuple[str, str]] = set()

    async_add_entities(
        SchneiderUPSNMCSensorEntity(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )

    @callback
    def add_environmental_probe_entities() -> None:
        """Add environmental probe sensors discovered from coordinator data."""
        if coordinator.data is None:
            return

        entities: list[SchneiderUPSNMCEnvironmentalProbeSensorEntity] = []
        for probe in coordinator.data.environmental_probes:
            for sensor_kind in _environmental_sensor_kinds(probe):
                key = (probe.index, sensor_kind)
                if key in environmental_entities:
                    continue

                environmental_entities.add(key)
                entities.append(
                    SchneiderUPSNMCEnvironmentalProbeSensorEntity(
                        coordinator,
                        probe,
                        sensor_kind,
                    )
                )

        if entities:
            async_add_entities(entities)

    add_environmental_probe_entities()
    entry.async_on_unload(
        coordinator.async_add_listener(add_environmental_probe_entities)
    )


class SchneiderUPSNMCSensorEntity(SchneiderUPSNMCEntity, SensorEntity):
    """An APC UPS NMC sensor."""

    entity_description: SchneiderUPSNMCSensorEntityDescription

    @property
    def available(self) -> bool:
        """Return whether the sensor has a fresh value."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.entity_description.value_fn(self.coordinator.data) is not None
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor state."""
        if self.coordinator.data is None:
            return None

        return self.entity_description.value_fn(self.coordinator.data)


class SchneiderUPSNMCEnvironmentalProbeSensorEntity(
    SchneiderUPSNMCEntity,
    SensorEntity,
):
    """An APC UPS NMC environmental probe sensor."""

    def __init__(
        self,
        coordinator: SchneiderUPSNMCCoordinator,
        probe: EnvironmentalProbe,
        sensor_kind: str,
    ) -> None:
        """Initialize the environmental probe sensor."""
        self._probe_index = probe.index
        self._sensor_kind = sensor_kind
        description = _environmental_probe_description(probe, sensor_kind)
        super().__init__(coordinator, description)
        self._update_probe_name(probe)

    @property
    def available(self) -> bool:
        """Return whether the environmental probe has a fresh value."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> int | None:
        """Return the environmental probe reading."""
        probe = self._probe()
        if probe is None or not probe.connected:
            return None

        if self._sensor_kind == "temperature":
            return probe.temperature
        if self._sensor_kind == "humidity":
            return probe.humidity

        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh dynamic probe metadata before writing updated state."""
        if probe := self._probe():
            self._update_probe_name(probe)

        super()._handle_coordinator_update()

    def _probe(self) -> EnvironmentalProbe | None:
        """Return the latest environmental probe data for this entity."""
        if self.coordinator.data is None:
            return None

        for probe in self.coordinator.data.environmental_probes:
            if probe.index == self._probe_index:
                return probe

        return None

    def _update_probe_name(self, probe: EnvironmentalProbe) -> None:
        """Update the translated name placeholder from latest probe metadata."""
        placeholders = {"probe_name": _environmental_probe_label(probe)}
        if self.translation_placeholders == placeholders:
            return

        self._attr_translation_placeholders = placeholders
        vars(self).pop("name", None)
        self._cached_friendly_name = None


def _environmental_sensor_kinds(probe: EnvironmentalProbe) -> tuple[str, ...]:
    """Return environmental sensor kinds that have values for one probe."""
    kinds: list[str] = []
    if probe.temperature is not None:
        kinds.append("temperature")
    if probe.humidity is not None:
        kinds.append("humidity")
    return tuple(kinds)


def _environmental_probe_description(
    probe: EnvironmentalProbe,
    sensor_kind: str,
) -> SensorEntityDescription:
    """Return an entity description for one environmental probe reading."""
    key = f"environment_probe_{_environmental_probe_key(probe.index)}_{sensor_kind}"
    if sensor_kind == "temperature":
        return SensorEntityDescription(
            key=key,
            translation_key="environment_probe_temperature",
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
        )

    return SensorEntityDescription(
        key=key,
        translation_key="environment_probe_humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
    )


def _environmental_probe_label(probe: EnvironmentalProbe) -> str:
    """Return the user-facing label for one environmental probe."""
    return probe.name or probe.location or f"Probe {probe.index}"


def _environmental_probe_key(index: str) -> str:
    """Return a stable entity key fragment for a probe table index."""
    return "_".join(
        part
        for part in ("".join(char if char.isalnum() else "_" for char in index)).split(
            "_"
        )
        if part
    )
