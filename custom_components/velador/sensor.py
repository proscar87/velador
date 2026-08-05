"""Sensores de Velador."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VeladorCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: VeladorCoordinator = entry.runtime_data
    async_add_entities(
        [
            ZombieCountSensor(coordinator),
            StaleCountSensor(coordinator),
            HealedTotalSensor(coordinator),
            WatchedSensor(coordinator),
        ]
    )


class VeladorSensor(CoordinatorEntity[VeladorCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: VeladorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "Velador",
            "manufacturer": "proscar87",
            "model": "Velador",
        }


class ZombieCountSensor(VeladorSensor):
    _attr_translation_key = "zombies"
    _attr_icon = "mdi:grave-stone"

    def __init__(self, coordinator: VeladorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_zombies"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.zombies) + len(self.coordinator.data.incurables)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "zombies": self.coordinator.data.zombies,
            "incurables": self.coordinator.data.incurables,
        }


class HealedTotalSensor(VeladorSensor):
    _attr_translation_key = "healed"
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, coordinator: VeladorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_healed"

    @property
    def native_value(self) -> int:
        return self.coordinator.data.healed_total


class WatchedSensor(VeladorSensor):
    _attr_translation_key = "watched"
    _attr_icon = "mdi:cctv"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: VeladorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_watched"

    @property
    def native_value(self) -> int:
        return self.coordinator.data.watched


class StaleCountSensor(VeladorSensor):
    _attr_translation_key = "stale"
    _attr_icon = "mdi:snowflake-alert"

    def __init__(self, coordinator: VeladorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_stale"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.stale)

    @property
    def extra_state_attributes(self) -> dict:
        return {"congelados": self.coordinator.data.stale}
