"""Signals the moment a rule fires. The rule's event entity (event.py)
listens for it.

A firing is seen in one of two ways, whichever comes first, and reported once
(logic.FireTracker):
  - Protect's live update stream: an "automation" update whose lastExecutedAt
    moved. This is the normal, immediate path.
  - the rule list that is polled anyway: its lastExecutedAt moved. This
    catches a firing the stream didn't deliver (it was down, or the poll got
    there first). After the stream reconnects the list is re-read at once.
    If a rule fired several times while the stream was down, that is
    reported as one firing (the latest).

The stream connection is the one shared by the Protect companions (Protect
Zones' stream.py); __init__ looks it up and hands it in.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .logic import FireTracker, match_history_row

if TYPE_CHECKING:
    from . import RulesCoordinator

_LOGGER = logging.getLogger(__name__)

DOMAIN = "protect_rules"
HISTORY_TIMEOUT = 5  # seconds to wait for what set the rule off
HISTORY_TRIES = 2  # the row can be written a moment after the rule fires


def rule_signal(rule_id: str) -> str:
    return f"{DOMAIN}_fired_{rule_id}"


class RuleFeed:
    def __init__(self, hass: HomeAssistant, coordinator: RulesCoordinator, stream) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.stream = stream  # Protect Zones' ProtectStream
        self.tracker = FireTracker()
        self._tasks: set[asyncio.Task] = set()
        self._unsub = None
        self._unsub_data = None

    def start(self) -> None:
        self.tracker.baseline(self.coordinator.data or {})
        self._unsub_data = self.coordinator.async_add_listener(self._on_data)
        self._unsub = self.stream.subscribe(self._handle, None, self._on_connect)

    @callback
    def stop(self) -> None:
        for unsub in (self._unsub, self._unsub_data):
            if unsub:
                unsub()
        self._unsub = self._unsub_data = None
        for task in self._tasks:
            task.cancel()

    def _run(self, coro, name: str) -> None:
        task = self.hass.async_create_background_task(coro, name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @callback
    def _on_connect(self) -> None:
        """The stream is (back) up: read the rules now to catch what it missed."""
        self._run(self.coordinator.async_request_refresh(), f"{DOMAIN} catch up")

    @callback
    def _on_data(self) -> None:
        """The rule list changed: report firings the stream didn't."""
        for rule_id, fired_at in self.tracker.poll_fires(self.coordinator.data or {}):
            self._run(self._send_fired(rule_id, fired_at), f"{DOMAIN} fired {rule_id}")

    @callback
    def _handle(self, action: dict[str, Any], data: Any) -> None:
        if not isinstance(action, dict) or action.get("modelKey") != "automation" or not isinstance(data, dict):
            return
        rule_id = action.get("id")
        rules = self.coordinator.data or {}
        rule = rules.get(rule_id)
        status = data.get("status")
        fired_at = status.get("lastExecutedAt") if isinstance(status, dict) else None
        if rule is None or not self.tracker.observe(rule_id, fired_at):
            return
        # show the new count / time on the rule's sensors right away (without
        # async_set_updated_data, which would also put off the next poll)
        merged = {**rule, **{k: {**(rule.get(k) or {}), **v} for k, v in data.items() if isinstance(v, dict)}}
        self.coordinator.data = {**rules, rule_id: merged}
        self.coordinator.async_update_listeners()
        self._run(self._send_fired(rule_id, fired_at), f"{DOMAIN} fired {rule_id}")

    async def _send_fired(self, rule_id: str, fired_at: float) -> None:
        """Signal that a rule fired, with what set it off (from its history:
        the row for this firing, not just the newest one)."""
        attrs: dict[str, Any] = {"fired_at": fired_at}
        try:
            async with asyncio.timeout(HISTORY_TIMEOUT):
                for attempt in range(HISTORY_TRIES):
                    if attempt:
                        await asyncio.sleep(0.5)
                    rows = await self.coordinator.api.api_request(f"automations/{rule_id}/history?limit=5")
                    row = match_history_row(rows, fired_at)
                    if row is not None:
                        attrs.update(self._describe_trigger(row))
                        break
                else:
                    _LOGGER.debug("No history row matches rule %s firing at %s", rule_id, fired_at)
        except Exception as err:  # noqa: BLE001 - the trigger still fires, with less detail
            _LOGGER.debug("Couldn't read what fired rule %s: %s", rule_id, err)
        async_dispatcher_send(self.hass, rule_signal(rule_id), attrs)

    def _describe_trigger(self, row: dict[str, Any]) -> dict[str, Any]:
        trig = row.get("trigger") or {}
        self.coordinator.refresh_devices()
        devices = self.coordinator.devices
        known = (self.coordinator.zones or {}).get(devices.ids.get(trig.get("device")), {})
        zones = []
        for kind in ("zone", "line", "loiter", "package"):
            for zid in (trig.get("zones") or {}).get(kind) or []:
                zones.append(next((z["name"] for z in known.get(kind, []) if z["id"] == zid), f"#{zid}"))
        src = trig.get("sourceEvent") or {}
        return {
            "trigger": trig.get("key"),
            "device": devices.label_by_id(trig.get("device")),
            "zones": zones,
            "detection_event_id": row.get("detectionEventId"),
            "detection_type": src.get("type"),
            "score": src.get("score"),
            "status": row.get("status"),
        }
