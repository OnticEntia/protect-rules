"""Shared base for Protect Rules entities."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, RulesCoordinator

DEVICE = DeviceInfo(
    identifiers={(DOMAIN, "alarm_manager")},
    name="Protect Alarm Manager",
    manufacturer="Ubiquiti",
    model="UniFi Protect rules",
    entry_type=DeviceEntryType.SERVICE,  # listed under Services, not among the cameras
)


def describe(rule: dict[str, Any]) -> dict[str, Any]:
    """Human-readable summary of a rule for entity attributes."""
    triggers = []
    for c in rule.get("conditions") or []:
        cond = c.get("condition") or {}
        triggers.append(cond.get("source") or cond.get("type"))
    actions = [a.get("type") for a in rule.get("actions") or []]
    cooldown = rule.get("cooldown") or {}
    return {
        "rule_id": rule["id"],
        "triggers": triggers,
        "actions": actions,
        "sources": len(rule.get("sources") or []),
        "scheduled": bool(rule.get("schedules")),
        "cooldown_enabled": cooldown.get("enable", False),
        "cooldown_minutes": round((cooldown.get("timeout") or 0) / 60000, 1),
        "blocked_by_arm_mode": rule.get("isBlockedByArmMode"),
        "editable": rule.get("editable"),
        "created_by_system": rule.get("isCreatedBySystem"),
    }


class RuleEntity(CoordinatorEntity[RulesCoordinator]):
    _attr_has_entity_name = True
    _attr_device_info = DEVICE
    _key = ""

    def __init__(self, coordinator: RulesCoordinator, rule_id: str) -> None:
        super().__init__(coordinator)
        self.rule_id = rule_id
        self._attr_unique_id = f"{self._key}_{rule_id}"

    @property
    def rule(self) -> dict[str, Any] | None:
        return self.coordinator.data.get(self.rule_id)

    @property
    def available(self) -> bool:
        return super().available and self.rule is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.rule:
            self._update_name(self.rule["name"])
        super()._handle_coordinator_update()

    def _update_name(self, rule_name: str) -> None:
        raise NotImplementedError


@callback
def add_new_rules(coordinator: RulesCoordinator, known: set[str], factory, async_add_entities) -> None:
    """Create entities for rules we haven't seen yet (rules added in Protect later)."""
    if coordinator.data:
        # forget rules that are gone (their entities are removed in __init__),
        # so one that comes back gets its entities again
        known.intersection_update(coordinator.data)
    new = [rid for rid in coordinator.data or {} if rid not in known]
    if new:
        known.update(new)
        async_add_entities([e for rid in new for e in factory(rid)])
