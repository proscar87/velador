"""Binary sensor de Velador: hay zombies detectados."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VeladorCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: VeladorCoordinator = entry.runtime_data
    async_add_entities([ZombieProblemSensor(coordinator)])


class ZombieProblemSensor(CoordinatorEntity[VeladorCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: VeladorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_problem"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "Velador",
            "manufacturer": "proscar87",
            "model": "Velador",
        }

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.data.zombies
            or self.coordinator.data.incurables
            or self.coordinator.data.stale
        )
