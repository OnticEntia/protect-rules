"""One event per rule: fires the moment the rule does, pushed live from
Protect (live.py), so automations can use it as a trigger."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ProtectRulesConfigEntry
from .entity import RuleEntity, add_new_rules
from .live import rule_signal


async def async_setup_entry(
    hass: HomeAssistant, entry: ProtectRulesConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    def factory(rule_id: str):
        return [RuleFired(coordinator, rule_id)]

    add_new_rules(coordinator, known, factory, async_add_entities)
    entry.async_on_unload(
        coordinator.async_add_listener(lambda: add_new_rules(coordinator, known, factory, async_add_entities))
    )


class RuleFired(RuleEntity, EventEntity):
    """What set the rule off (trigger, device, zones, score) is in the attributes."""

    _key = "fired"
    _attr_icon = "mdi:shield-alert"
    _attr_event_types = ["fired"]

    def __init__(self, coordinator, rule_id: str) -> None:
        super().__init__(coordinator, rule_id)
        self._update_name(coordinator.data[rule_id]["name"])

    def _update_name(self, rule_name: str) -> None:
        self._attr_name = f"{rule_name} fired"

    @property
    def available(self) -> bool:
        # Not tied to the last poll having worked: firings are pushed, and an
        # entity that flickers to unavailable and back looks like a change to
        # automations watching it.
        return self.rule is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, rule_signal(self.rule_id), self._fired))

    @callback
    def _fired(self, attrs: dict[str, Any]) -> None:
        self._trigger_event("fired", attrs)
        self.async_write_ha_state()
