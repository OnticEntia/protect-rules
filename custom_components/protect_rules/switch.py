"""One switch per Protect rule: on = rule enabled."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ProtectRulesConfigEntry
from .entity import RuleEntity, add_new_rules, describe


async def async_setup_entry(
    hass: HomeAssistant, entry: ProtectRulesConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    def factory(rule_id: str):
        return [RuleSwitch(coordinator, rule_id)]

    add_new_rules(coordinator, known, factory, async_add_entities)
    entry.async_on_unload(
        coordinator.async_add_listener(lambda: add_new_rules(coordinator, known, factory, async_add_entities))
    )


class RuleSwitch(RuleEntity, SwitchEntity):
    _key = "rule"
    _attr_icon = "mdi:shield-alert-outline"

    def __init__(self, coordinator, rule_id: str) -> None:
        super().__init__(coordinator, rule_id)
        self._update_name(coordinator.data[rule_id]["name"])

    def _update_name(self, rule_name: str) -> None:
        self._attr_name = rule_name

    @property
    def is_on(self) -> bool | None:
        return bool(self.rule["enable"]) if self.rule else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return describe(self.rule) if self.rule else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_edit(self.rule_id, lambda rule: {"enable": True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_edit(self.rule_id, lambda rule: {"enable": False})
