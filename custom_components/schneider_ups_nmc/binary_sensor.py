"""Binary sensors for APC UPS NMC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass

from .entity import SchneiderUPSNMCEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SchneiderUPSNMCConfigEntry
    from .coordinator import SchneiderUPSNMCCoordinator
    from .snmp import UPSData


@dataclass(frozen=True, kw_only=True)
class SchneiderUPSNMCBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe an APC UPS NMC binary sensor."""

    value_fn: Callable[[UPSData], bool | None]


def _on_battery(data: UPSData) -> bool | None:
    """Return whether the UPS is currently running on battery."""
    output_source = data.value("output_source")
    ups_status = data.value("ups_status")
    seconds_on_battery = data.value("seconds_on_battery")

    if output_source is None and ups_status is None and seconds_on_battery is None:
        return None

    return (
        output_source == "battery"
        or ups_status in {"on_battery", "on_battery_test"}
        or bool(seconds_on_battery)
    )


def _battery_low(data: UPSData) -> bool | None:
    """Return whether the UPS battery is low or depleted."""
    battery_status = data.value("battery_status")
    if battery_status is None:
        return None

    return battery_status in {"low", "depleted"}


def _alarm_present(data: UPSData) -> bool | None:
    """Return whether the UPS reports one or more active alarms."""
    alarm_count = data.value("alarm_count")
    if alarm_count is None:
        return None

    return int(alarm_count) > 0


def _battery_needs_replacing(data: UPSData) -> bool | None:
    """Return whether the UPS battery needs replacing."""
    battery_replace_indicator = data.value("battery_replace_indicator")
    if battery_replace_indicator is None:
        return None

    return battery_replace_indicator == "needs_replacement"


BINARY_SENSOR_DESCRIPTIONS: tuple[SchneiderUPSNMCBinarySensorEntityDescription, ...] = (
    SchneiderUPSNMCBinarySensorEntityDescription(
        key="on_battery",
        translation_key="on_battery",
        value_fn=_on_battery,
    ),
    SchneiderUPSNMCBinarySensorEntityDescription(
        key="battery_low",
        translation_key="battery_low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_battery_low,
    ),
    SchneiderUPSNMCBinarySensorEntityDescription(
        key="battery_needs_replacing",
        translation_key="battery_needs_replacing",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_battery_needs_replacing,
    ),
    SchneiderUPSNMCBinarySensorEntityDescription(
        key="alarm_present",
        translation_key="alarm_present",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_alarm_present,
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: SchneiderUPSNMCConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up APC UPS NMC binary sensors."""
    coordinator: SchneiderUPSNMCCoordinator = entry.runtime_data
    async_add_entities(
        SchneiderUPSNMCBinarySensorEntity(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class SchneiderUPSNMCBinarySensorEntity(SchneiderUPSNMCEntity, BinarySensorEntity):
    """An APC UPS NMC binary sensor."""

    entity_description: SchneiderUPSNMCBinarySensorEntityDescription

    @property
    def available(self) -> bool:
        """Return whether the binary sensor has a fresh value."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.entity_description.value_fn(self.coordinator.data) is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Return the sensor state."""
        if self.coordinator.data is None:
            return None

        return self.entity_description.value_fn(self.coordinator.data)
