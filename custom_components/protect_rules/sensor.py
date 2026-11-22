"""Per-rule activity sensors: how often it fired in the last 24 hours, and when last."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ProtectRulesConfigEntry
from .entity import RuleEntity, add_new_rules


async def async_setup_entry(
    hass: HomeAssistant, entry: ProtectRulesConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    def factory(rule_id: str):
        return [RuleHits(coordinator, rule_id), RuleLastFired(coordinator, rule_id)]

    add_new_rules(coordinator, known, factory, async_add_entities)
    entry.async_on_unload(
        coordinator.async_add_listener(lambda: add_new_rules(coordinator, known, factory, async_add_entities))
    )


class RuleHits(RuleEntity, SensorEntity):
    _key = "hits"
    _attr_icon = "mdi:counter"
    # Protect's count covers the last 24 hours, so it goes down as well as up
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "hits"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, rule_id: str) -> None:
        super().__init__(coordinator, rule_id)
        self._update_name(coordinator.data[rule_id]["name"])

    def _update_name(self, rule_name: str) -> None:
        self._attr_name = f"{rule_name} hits"

    @property
    def native_value(self) -> int | None:
        return ((self.rule or {}).get("status") or {}).get("total")


class RuleLastFired(RuleEntity, SensorEntity):
    _key = "last"
    _attr_icon = "mdi:clock-alert-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, rule_id: str) -> None:
        super().__init__(coordinator, rule_id)
        self._update_name(coordinator.data[rule_id]["name"])

    def _update_name(self, rule_name: str) -> None:
        self._attr_name = f"{rule_name} last fired"

    @property
    def native_value(self) -> datetime | None:
        ms = ((self.rule or {}).get("status") or {}).get("lastExecutedAt")
        return datetime.fromtimestamp(ms / 1000, tz=UTC) if ms else None
