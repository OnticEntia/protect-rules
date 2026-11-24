"""Protect Rules: UniFi Protect Alarm Manager rules in Home Assistant.

For every Alarm Manager rule ("automation" in Protect's API):
  switch  — rule enabled / disabled
  sensor  — total times it fired, and when it last fired
  event   — fires the moment the rule does (what set it off as attributes)
with the rule's triggers, actions, schedule and cooldown as attributes.

The rule events are pushed live from Protect (live.py) so automations can use
them as triggers; everything else is polled.

A companion to the UniFi Protect integration. The per-zone events and
occupancy sensors are in its sibling, Protect Zones, whose connection to
Protect's live stream this one shares.

It reuses the logged-in client of HA's own UniFi Protect integration, so it
holds no credentials of its own. It uses Protect's internal API (the one the
Protect app uses), which is undocumented: a Protect update could change it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import time
import uuid
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.loader import IntegrationNotFound, async_get_integration

from .cards import CardsView, async_card_urls, load_cards, unload_cards
from .live import RuleFeed
from .logic import Devices, Outage, fingerprint, merge_rules, parse_rules, rule_devices

_LOGGER = logging.getLogger(__name__)

DOMAIN = "protect_rules"
PLATFORMS = [Platform.SWITCH, Platform.SENSOR, Platform.EVENT]
SCAN_INTERVAL = timedelta(seconds=30)
ZONES_REFRESH = 300  # seconds
ZONES_DOMAIN = "protect_zones"  # the companion whose live stream connection is shared
CARD_URLS = "protect_rules_card_urls"
DEVICE_STORE = "protect_rules_devices"  # names of devices seen, to name one that is removed later
DEVICE_GROUPS = ("cameras", "lights", "sensors", "chimes", "doorlocks")

type ProtectRulesConfigEntry = ConfigEntry[RulesCoordinator]


def _protect_api(hass: HomeAssistant):
    for entry in hass.config_entries.async_entries("unifiprotect"):
        if entry.state is ConfigEntryState.LOADED and getattr(entry, "runtime_data", None):
            return entry.runtime_data.api
    return None


async def async_zones_stream(hass: HomeAssistant):
    """Protect Zones' stream module, or None if Protect Zones isn't installed.

    Protect Zones is a separate custom integration, so it can't be listed in
    this one's manifest (the manifest check only knows integrations in this
    repository and in Home Assistant itself); it is looked up here instead.
    Only its code is needed, not a configured Protect Zones entry."""
    try:
        integration = await async_get_integration(hass, ZONES_DOMAIN)
        return await integration.async_get_platform("stream")
    except (IntegrationNotFound, ImportError):
        return None


class RuleError(HomeAssistantError):
    """A change that can't be made; code is what the card is told."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RulesCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Polls the rule list; data is {rule_id: rule}.

    A rule a read leaves out stays in data until it has been missing several
    reads in a row (logic.merge_rules), so one odd answer removes nothing.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL, config_entry=entry)
        self._misses: dict[str, int] = {}  # rule -> reads in a row it was missing from
        self._writes = 0  # goes up with every change made here; a read that spans one is stale
        self._locks: dict[str, asyncio.Lock] = {}  # one change at a time per rule
        self._outage = Outage()  # a console that briefly doesn't answer is ridden out
        self.devices = Devices()  # what Protect has now, and the names of what it had
        self._device_store: Store[dict[str, Any]] = Store(hass, 1, DEVICE_STORE)
        self.zones: dict[str, dict[str, list[dict[str, Any]]]] | None = None
        self._zones_at = 0.0
        self.ptz: dict[str, dict[str, Any]] = {}
        self.caps: dict[str, list[str]] | None = None  # device -> triggers it can produce
        self.schedules: list[dict[str, Any]] = []  # Protect's named schedules
        self.people: dict[str, list[dict[str, str]]] = {"faces": [], "vehicles": [], "users": []}

    @property
    def api(self):
        api = _protect_api(self.hass)
        if api is None:
            raise UpdateFailed("UniFi Protect integration isn't loaded")
        return api

    async def async_load_devices(self) -> None:
        """Bring back the device names remembered before the last restart."""
        saved = await self._device_store.async_load()
        names = (saved or {}).get("names")
        if isinstance(names, dict):
            self.devices = Devices({k: v for k, v in names.items() if isinstance(k, str) and isinstance(v, str)})
        self.refresh_devices()

    @callback
    def refresh_devices(self) -> None:
        """Look at which devices Protect has right now (from the UniFi
        Protect integration, which is told of adoptions and removals as they
        happen). A device that came or went makes the per-camera lists (zones,
        PTZ presets, what each can detect) be read again at the next poll, so
        a newly adopted camera is usable without a restart and a removed one
        drops out of them."""
        found: list[tuple[str, str, str, bool]] | None = []
        try:
            boot = self.api.bootstrap
            for group in DEVICE_GROUPS:
                for dev in (getattr(boot, group, None) or {}).values():
                    found.append((dev.mac, dev.id, dev.display_name, bool(getattr(dev, "is_connected", True))))
        except Exception:  # noqa: BLE001 - then nothing is called removed
            found = None
        changed, learned = self.devices.update(found)
        if changed:
            self._zones_at = 0.0
        if learned:
            self._device_store.async_delay_save(lambda: {"names": dict(self.devices.remembered)}, 30)

    async def _read_rules(self) -> dict[str, dict[str, Any]]:
        """The rule list straight from Protect, checked for shape."""
        rules = await self.api.api_request("automations")
        try:
            return parse_rules(rules)
        except ValueError as err:
            raise UpdateFailed(f"Protect gave an unexpected answer for the rules: {err}") from err

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        writes = self._writes
        try:
            rules = await self._read_rules()
        except Exception as err:
            reason = str(err) if isinstance(err, UpdateFailed) else f"Couldn't read Protect rules: {err}"
            # The console restarting or a timeout: keep the rules as they
            # were for a few reads (one warning), and only call it a failure
            # (entities unavailable, one error from the coordinator) if it lasts.
            verdict = self._outage.failed(self.data is not None)
            if verdict == "fail":
                raise UpdateFailed(reason) from err
            if verdict == "warn":
                _LOGGER.warning("Protect isn't answering; keeping the last known rules for now. %s", reason)
            return self.data
        if (missed := self._outage.succeeded()) and self.last_update_success:
            _LOGGER.info("Protect is answering again (after %s missed reads)", missed)
        self.refresh_devices()
        await self._load_zones()
        for rule_id in [r for r, lock in self._locks.items() if r not in rules and not lock.locked()]:
            del self._locks[rule_id]
        if writes != self._writes and self.data is not None:
            # a change was made here while this read was under way: it may
            # show the rules as they were before, so keep what we have
            return self.data
        return merge_rules(self.data, rules, self._misses)

    async def _load_zones(self) -> None:
        """Each camera's detection zones, lines and loiter zones (a rule's scope
        can be narrowed to them). Re-read every few minutes; never fatal."""
        now = time.monotonic()
        if self.zones is not None and now - self._zones_at < ZONES_REFRESH:
            return
        try:
            cameras = await self.api.api_request("cameras")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Couldn't read camera zones: %s", err)
            return
        self._zones_at = now
        try:
            cameras = [cam for cam in cameras or [] if isinstance(cam, dict)]
            self.zones = {
                cam["mac"]: {
                    kind: [
                        {"id": z["id"], "name": (z.get("name") or "").strip() or f"#{z['id']}", "color": z.get("color")}
                        for z in cam.get(key) or []
                        if isinstance(z, dict) and isinstance(z.get("id"), int)
                    ]
                    for kind, key in (("zone", "smartDetectZones"), ("line", "smartDetectLines"), ("loiter", "smartDetectLoiterZones"))
                }
                for cam in cameras
                if cam.get("mac")
            }
        except Exception as err:  # noqa: BLE001 - labels and pickers only
            _LOGGER.debug("Couldn't make sense of the camera zones: %s", err)
            return
        # PTZ cameras: their saved presets and patrols, for the PTZ action
        ptz: dict[str, dict[str, Any]] = {}
        for cam in cameras or []:
            if not (cam.get("featureFlags") or {}).get("isPtz") or not cam.get("mac"):
                continue
            lists: dict[str, list[dict[str, Any]]] = {}
            for key, path in (("presets", "preset"), ("patrols", "patrol")):
                try:
                    rows = await self.api.api_request(f"cameras/{cam['id']}/ptz/{path}")
                except Exception:  # noqa: BLE001
                    rows = []
                lists[key] = [
                    {"id": r["id"], "name": r.get("name") or f"#{r.get('slot', '')}"}
                    for r in rows or []
                    if r.get("id") and (key == "presets" or len(r.get("presets") or []) > 1)
                ]
            ptz[cam["mac"]] = lists
        self.ptz = ptz
        caps = {cam["mac"]: _camera_triggers(cam) for cam in cameras or [] if cam.get("mac")}
        for kind, triggers in (("lights", ["light_motion"]), ("sensors", SENSOR_TRIGGERS)):
            try:
                for dev in await self.api.api_request(kind) or []:
                    if dev.get("mac"):
                        caps[dev["mac"]] = list(triggers)
            except Exception:  # noqa: BLE001
                pass
        self.caps = caps
        # who and what a rule can be narrowed to: named faces, named vehicles,
        # and the Protect users whose phone location drives geofencing
        people: dict[str, list[dict[str, str]]] = {"faces": [], "vehicles": [], "users": []}
        for key, path in (("faces", "face"), ("vehicles", "vehicle")):
            try:
                res = await self.api.api_request(f"recognition/{path}/groups?hasName=true&pageSize=1000")
                people[key] = sorted(
                    (
                        {"id": g["id"], "name": g.get("name") or g.get("matchedName")}
                        for g in (res or {}).get("groups") or []
                        if g.get("id") and (g.get("name") or g.get("matchedName"))
                    ),
                    key=lambda g: g["name"].lower(),
                )
            except Exception:  # noqa: BLE001
                pass
        try:
            people["users"] = [
                {"id": u["id"], "name": u["name"]}
                for u in await self.api.api_request("users") or []
                if u.get("id") and u.get("name") and u.get("email")
            ]
        except Exception:  # noqa: BLE001
            pass
        self.people = people
        # the named ("predefined") schedules a rule can follow
        try:
            rows = await self.api.api_request("automations/schedules")
            self.schedules = [
                {"id": r["id"], "name": r.get("name") or "Schedule", "schedules": r.get("schedules") or []}
                for r in rows or []
                if r.get("id")
            ]
        except Exception:  # noqa: BLE001
            pass

    async def async_create(self, rule: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self.api.api_request("automations", method="post", json=rule)
        except Exception as err:
            raise HomeAssistantError(f"Protect rejected the new rule: {err}") from err
        finally:
            self._writes += 1
        if isinstance(resp, dict) and resp.get("id"):
            self.async_set_updated_data({**(self.data or {}), resp["id"]: resp})
        await self.async_request_refresh()
        return resp if isinstance(resp, dict) else {}

    async def async_delete(self, rule_id: str) -> None:
        async with self._locks.setdefault(rule_id, asyncio.Lock()):
            try:
                # Protect answers a delete with an empty body, so don't parse it
                await self.api.api_request_raw(f"automations/{rule_id}", method="delete")
            except Exception as err:
                raise HomeAssistantError(f"Protect wouldn't delete the rule: {err}") from err
            finally:
                self._writes += 1
            data = dict(self.data or {})
            data.pop(rule_id, None)
            self._misses.pop(rule_id, None)
            self.async_set_updated_data(data)
        self._locks.pop(rule_id, None)
        await self.async_request_refresh()

    async def async_edit(
        self, rule_id: str, build: Callable[[dict[str, Any]], dict[str, Any]], base: str | None = None
    ) -> None:
        """Change a rule. One change at a time per rule, each worked out from
        the rule as Protect has it right now (not from the last poll), so two
        changes can't undo each other. build(rule) returns what to change.
        base, if given, is the fingerprint of the rule the caller was looking
        at: the change is refused if the rule is no longer that."""
        async with self._locks.setdefault(rule_id, asyncio.Lock()):
            try:
                rule = (await self._read_rules()).get(rule_id)
            except Exception as err:
                raise RuleError("unreadable", f"Couldn't read the rule from Protect: {err}") from err
            if rule is None:
                raise RuleError("not_found", "No such rule")
            if base is not None and fingerprint(rule) != base:
                raise RuleError(
                    "changed", "This rule was changed somewhere else since you opened it. Cancel, then edit it again."
                )
            changes = build(rule)
            if not changes:
                raise RuleError("nothing", "Nothing to change")
            await self._patch(rule_id, rule, changes)
        await self.async_request_refresh()

    async def _patch(self, rule_id: str, rule: dict[str, Any], changes: dict[str, Any]) -> None:
        try:
            resp = await self.api.api_request(f"automations/{rule_id}", method="patch", json=changes)
        except Exception as err:
            raise HomeAssistantError(f"Protect rejected the change: {err}") from err
        finally:
            self._writes += 1
        # Show the change immediately (Protect returns the updated rule), then
        # re-read in the background; a plain refresh is debounced and can lag.
        data = dict(self.data or {})
        if isinstance(resp, dict) and resp.get("id") == rule_id and isinstance(resp.get("name"), str):
            data[rule_id] = resp
        else:
            data[rule_id] = {**rule, **changes}
        self._misses.pop(rule_id, None)
        self.async_set_updated_data(data)


MAC = vol.Match(r"^[0-9A-F]{12}$")
TRIGGER = vol.All(str, vol.Match(r"^[a-z_]+$"))
TRIGGER_VALUES = {TRIGGER: vol.Any(vol.All(str, vol.Length(min=1, max=20)), vol.All([vol.All(str, vol.Length(min=1, max=80))], vol.Length(min=1, max=60)))}
ACTION_SCHEMA = vol.Any(
    {vol.Required("kind"): "notify", vol.Optional("push", default=False): bool, vol.Optional("email", default=False): bool},
    {vol.Required("kind"): "light", vol.Required("device"): MAC, vol.Optional("seconds", default=30): vol.All(int, vol.Range(5, 3600))},
    {
        vol.Required("kind"): "webhook",
        vol.Required("url"): vol.All(str, vol.Match(r"^https?://\S+$"), vol.Length(max=500)),
        vol.Optional("method", default="POST"): vol.In(("POST", "GET")),
    },
    {
        vol.Required("kind"): "ptz",
        vol.Required("device"): MAC,
        vol.Required("mode"): vol.In(("preset", "patrol", "autotrack")),
        vol.Optional("preset_id"): str,
        vol.Optional("return_home", default=10): vol.All(int, vol.Range(10, 60)),  # seconds
        vol.Optional("patrol_id"): str,
        vol.Optional("repeat", default=1): vol.All(int, vol.Range(1, 3)),
        vol.Optional("enable", default=True): bool,
    },
    {vol.Required("kind"): "keep", vol.Required("index"): int},  # an existing action this UI can't edit
)
RULE_FIELDS = {
    vol.Optional("triggers"): vol.All([TRIGGER], vol.Length(min=1, max=12)),
    # a trigger's setting where it has one, e.g. {"speed_mph": "20"}; a list
    # narrows it to those faces / vehicles / people (one condition each),
    # e.g. {"face_known": ["face_12", "face_31"]}
    vol.Optional("trigger_values"): TRIGGER_VALUES,
    # "AND" steps: after one of the triggers above, one of these must also
    # happen within so many seconds (Protect: historyConditions)
    vol.Optional("also"): vol.All(
        [
            {
                vol.Required("triggers"): vol.All([TRIGGER], vol.Length(min=1, max=12)),
                vol.Optional("trigger_values"): TRIGGER_VALUES,
                vol.Optional("seconds", default=1): vol.All(int, vol.Range(1, 60)),
            }
        ],
        vol.Length(max=3),
    ),
    # when the rule is active: always, one of Protect's named schedules, or
    # weekly blocks (days 0 = Sunday … 6, [hour, minute] start and end)
    vol.Optional("schedule"): vol.Any(
        {vol.Required("mode"): "always"},
        {vol.Required("mode"): "predefined", vol.Required("id"): str},
        {
            vol.Required("mode"): "custom",
            vol.Required("blocks"): vol.All(
                [
                    {
                        vol.Required("days"): vol.All([vol.All(int, vol.Range(0, 6))], vol.Length(min=1, max=7)),
                        vol.Required("start"): vol.ExactSequence([vol.All(int, vol.Range(0, 23)), vol.All(int, vol.Range(0, 59))]),
                        vol.Required("end"): vol.ExactSequence([vol.All(int, vol.Range(0, 23)), vol.All(int, vol.Range(0, 59))]),
                    }
                ],
                vol.Length(min=1, max=14),
            ),
        },
    ),
    vol.Optional("scope"): vol.In(("include", "exclude")),
    # per device: which of its zones / lines / loiter zones the rule is limited to
    vol.Optional("zones"): {MAC: {vol.In(("zone", "line", "loiter")): [int]}},
    vol.Optional("actions"): vol.All([ACTION_SCHEMA], vol.Length(max=6)),
}


SET_COOLDOWN_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required("enabled"): cv.boolean,
        vol.Optional("minutes", default=10): vol.All(vol.Coerce(float), vol.Range(0.5, 1440)),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ProtectRulesConfigEntry) -> bool:
    stream = await async_zones_stream(hass)
    if stream is None:
        raise ConfigEntryError("Protect Zones isn't installed. Install it, restart Home Assistant, then reload Protect Rules.")
    if _protect_api(hass) is None:
        raise ConfigEntryNotReady("Waiting for the UniFi Protect integration")
    coordinator = RulesCoordinator(hass, entry)
    await coordinator.async_load_devices()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    feed = RuleFeed(hass, coordinator, stream.async_get_stream(hass))
    feed.start()
    entry.async_on_unload(feed.stop)

    @callback
    def prune() -> None:
        """Drop the entities of rules that were deleted (here or in Protect).
        A rule only leaves coordinator.data once it was deleted here or has
        been missing from several good reads in a row; and if that leaves no
        rules at all, nothing is removed."""
        if not coordinator.data:
            return
        registry = er.async_get(hass)
        for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
            if ent.unique_id.startswith("zone_"):
                # a camera zone from before those moved to Protect Zones
                registry.async_remove(ent.entity_id)
                continue
            if ent.unique_id.split("_", 1)[-1] not in coordinator.data:
                registry.async_remove(ent.entity_id)

    prune()
    entry.async_on_unload(coordinator.async_add_listener(prune))
    # ...and the per-camera "Protect Zones" devices that held them
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if any(d == DOMAIN and i.startswith("zones_") for d, i in device.identifiers):
            devices.async_remove_device(device.id)

    async def set_cooldown(call: ServiceCall) -> None:
        """Set how long a rule stays quiet after firing."""
        registry = er.async_get(hass)
        for entity_id in call.data[ATTR_ENTITY_ID]:
            ent = registry.async_get(entity_id)
            if ent is None or ent.platform != DOMAIN:
                raise HomeAssistantError(f"{entity_id} isn't a Protect Rules entity")
            rule_id = ent.unique_id.split("_", 1)[1]

            def build(rule: dict[str, Any]) -> dict[str, Any]:
                cooldown = dict(rule.get("cooldown") or {})
                cooldown["enable"] = call.data["enabled"]
                cooldown["timeout"] = int(call.data["minutes"] * 60_000)
                cooldown.pop("lastExecutedAt", None)
                return {"cooldown": cooldown}

            try:
                await coordinator.async_edit(rule_id, build)
            except RuleError as err:
                if err.code == "not_found":
                    raise HomeAssistantError(f"Rule for {entity_id} no longer exists") from err
                raise

    # it changes rules on the NVR, like the (admin-only) card does
    async_register_admin_service(hass, DOMAIN, "set_cooldown", set_cooldown, schema=SET_COOLDOWN_SCHEMA)
    # cards that were open before a reload carry on with the new coordinator
    subs: set[_Subscription] = hass.data.setdefault(SUBSCRIPTIONS, set())
    hass.data[ACTIVE] = coordinator
    for sub in list(subs):
        sub.attach(coordinator)

    @callback
    def release() -> None:
        hass.data.pop(ACTIVE, None)
        for sub in list(subs):
            sub.detach()

    entry.async_on_unload(release)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_update)
    websocket_api.async_register_command(hass, ws_create)
    websocket_api.async_register_command(hass, ws_delete)
    websocket_api.async_register_command(hass, ws_history)
    # the dashboard card comes with the integration (cards.py)
    if not hass.data.get(f"{DOMAIN}_view"):
        hass.http.register_view(CardsView())
        hass.data[f"{DOMAIN}_view"] = True
    hass.data[CARD_URLS] = await async_card_urls(hass)
    load_cards(hass, hass.data[CARD_URLS])
    return True


AUDIO_TRIGGERS = {
    "alrmSmoke": "audio_alarm_smoke",
    "alrmCmonx": "audio_alarm_co",
    "alrmSiren": "audio_alarm_siren",
    "alrmBabyCry": "audio_alarm_baby_cry",
    "alrmSpeak": "audio_alarm_speak",
    "alrmBurglar": "audio_alarm_burglar",
    "alrmCarHorn": "audio_alarm_car_horn",
    "alrmBark": "audio_alarm_bark",
    "alrmGlassBreak": "audio_alarm_glass_break",
}
SENSOR_TRIGGERS = [
    "sensor_motion", "sensor_door_opened", "sensor_door_closed", "sensor_alarm", "sensor_alarm_smoke",
    "sensor_alarm_co", "sensor_alarm_glassbreak", "sensor_water_leak", "sensor_extreme_value",
    "sensor_battery_low", "sensor_tamper", "sensor_button_pressed",
]


def _camera_triggers(cam: dict[str, Any]) -> list[str]:
    """Which rule triggers this camera can produce, going by what it supports
    and what is switched on in its detection settings (as Protect's editor does)."""
    flags = cam.get("featureFlags") or {}
    smart = cam.get("smartDetectSettings") or {}
    objects = set(smart.get("objectTypes") or [])
    extended = set((cam.get("extendedAiFeatures") or {}).get("smartDetectTypes") or [])
    ai_port = bool(cam.get("isPairedWithAiPort"))
    out = ["motion"]
    out += [t for t in ("person", "vehicle", "animal", "package") if t in objects]
    if "face" in objects or "face" in extended or ai_port:
        out += ["face_unknown", "face_known", "face_of_interest"]
    if "licensePlate" in objects or "licensePlate" in extended or ai_port:
        out += ["license_plate_unknown", "license_plate_known", "license_plate_of_interest"]
    if objects:
        out.append("line_crossed")
        if "smartDetectLoiterZones" in cam:
            out.append("smart_loiter_detection")
    elif flags.get("hasLineCrossing"):
        out.append("line_crossed")
    if flags.get("hasLiveviewTracking"):
        out += [f"{t}_idle_time" for t in ("person", "vehicle") if t in objects]
    audio = [AUDIO_TRIGGERS[a] for a in smart.get("audioTypes") or [] if a in AUDIO_TRIGGERS]
    if audio:
        out += ["audio_alarm", *audio]
    if flags.get("supportNfc"):
        out += ["nfc_registered", "nfc_unknown"]
    if flags.get("hasFingerprintSensor"):
        out += ["fingerprint_registered", "fingerprint_unknown"]
    if flags.get("isDoorbell"):
        out.append("ring")
    if ((flags.get("hotplug") or {}).get("extender") or {}).get("hasRadar"):
        out += ["speed_mph", "speed_kmph"]
    if flags.get("hasTamperDetection") and smart.get("enableTamperDetection"):
        out.append("smart_tamper_detection")
    return out


def _coordinator(hass: HomeAssistant) -> RulesCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    return None


def _payload(hass: HomeAssistant, coordinator: RulesCoordinator) -> dict[str, Any]:
    """The rules as Protect stores them, plus what the card needs to label them."""
    coordinator.refresh_devices()
    known = coordinator.devices
    rules = coordinator.data or {}
    registry = er.async_get(hass)
    entities = {
        rid: registry.async_get_entity_id("switch", DOMAIN, f"rule_{rid}") for rid in coordinator.data or {}
    }
    # where Protect is reached, for the webhook trigger link
    protect_host = None
    try:
        protect_host = str(coordinator.api._host)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass
    return {
        "loaded": True,
        "rules": list(rules.values()),
        # what each rule looked like, for the edit form to say what it started from
        "revs": {rid: fingerprint(rule) for rid, rule in rules.items()},
        # the devices Protect has now (what a rule can be given) ...
        "devices": dict(known.names),
        "offline": sorted(known.offline),
        # ... a name for every device a rule names, also one Protect no longer has ...
        "labels": {mac: known.label(mac) for rule in rules.values() for mac in rule_devices(rule)},
        # ... and which of those are gone: {mac: last known name or null}
        "removed": known.removed_in(rules),
        "zones": coordinator.zones or {},
        "ptz": coordinator.ptz,
        "caps": coordinator.caps,
        "schedules": coordinator.schedules,
        "people": coordinator.people,
        "entities": entities,
        "protect_host": protect_host,
    }


SUBSCRIPTIONS = "protect_rules_subscriptions"
ACTIVE = "protect_rules_active"  # the coordinator subscriptions should follow


class _Subscription:
    """One card's subscription. It outlives the integration being reloaded:
    it is told {"loaded": false} when Protect Rules unloads and is attached to
    the new coordinator when it is set up again."""

    def __init__(self, hass: HomeAssistant, connection, msg_id: int) -> None:
        self.hass = hass
        self.connection = connection
        self.msg_id = msg_id
        self.coordinator: RulesCoordinator | None = None
        self._unsub: Callable[[], None] | None = None

    @callback
    def attach(self, coordinator: RulesCoordinator) -> None:
        self.detach(tell=False)
        self.coordinator = coordinator
        self._unsub = coordinator.async_add_listener(self.push)
        self.push()

    @callback
    def detach(self, tell: bool = True) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        self.coordinator = None
        if tell:
            self.connection.send_message(websocket_api.event_message(self.msg_id, {"loaded": False}))

    @callback
    def push(self) -> None:
        if self.coordinator is not None:
            self.connection.send_message(
                websocket_api.event_message(self.msg_id, _payload(self.hass, self.coordinator))
            )

    @callback
    def close(self) -> None:
        self.detach(tell=False)
        self.hass.data.get(SUBSCRIPTIONS, set()).discard(self)


@websocket_api.websocket_command({vol.Required("type"): "protect_rules/subscribe"})
@websocket_api.require_admin
@callback
def ws_subscribe(hass: HomeAssistant, connection, msg) -> None:
    """Send the rule list now and again whenever it changes; across reloads
    of the integration too."""
    sub = _Subscription(hass, connection, msg["id"])
    hass.data.setdefault(SUBSCRIPTIONS, set()).add(sub)
    connection.subscriptions[msg["id"]] = sub.close
    connection.send_result(msg["id"])
    coordinator = hass.data.get(ACTIVE)
    if coordinator is None:
        sub.detach()  # says it isn't loaded; the rules follow once it is
    else:
        sub.attach(coordinator)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "protect_rules/update",
        vol.Required("rule_id"): str,
        vol.Optional("base"): vol.All(str, vol.Length(max=64)),
        vol.Optional("enable"): bool,
        vol.Optional("push"): bool,
        vol.Optional("email"): bool,
        vol.Optional("cooldown_enabled"): bool,
        vol.Optional("cooldown_minutes"): vol.All(vol.Coerce(float), vol.Range(0.5, 1440)),
        vol.Optional("name"): vol.All(str, vol.Length(min=1, max=80)),
        vol.Optional("trigger"): vol.All(str, vol.Match(r"^[a-z_]+$")),
        vol.Optional("devices"): [vol.Match(r"^[0-9A-F]{12}$")],
        vol.Optional("action"): vol.In(("notify", "light")),
        vol.Optional("light_device"): vol.Match(r"^[0-9A-F]{12}$"),
        vol.Optional("light_seconds"): vol.All(int, vol.Range(5, 3600)),
        **RULE_FIELDS,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_update(hass: HomeAssistant, connection, msg) -> None:
    """Change a rule: on/off, my push/email notifications, repeat cooldown,
    or (from the edit form) its name, triggers, schedule, scope and actions.
    "base" is the rev of the rule the edit form started from."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "No such rule")
        return
    try:
        await coordinator.async_edit(msg["rule_id"], lambda rule: _changes(coordinator, rule, msg), msg.get("base"))
    except RuleError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "rejected", str(err))
        return
    connection.send_result(msg["id"])


def _changes(coordinator: RulesCoordinator, rule: dict[str, Any], msg: dict[str, Any]) -> dict[str, Any]:
    """What to send Protect for an update request, worked out from the rule
    as it is now. Raises RuleError for a request that can't be met."""
    changes: dict[str, Any] = {}
    if "enable" in msg:
        changes["enable"] = msg["enable"]
    if "name" in msg:
        changes["name"] = msg["name"].strip()
    if "trigger" in msg:
        conditions = rule.get("conditions") or []
        current = (conditions[0].get("condition") or {}).get("source") if len(conditions) == 1 else None
        if len(conditions) != 1:
            raise RuleError("multi", "This rule has several triggers; change them in Protect")
        if msg["trigger"] != current:
            condition: dict[str, Any] = {"type": "is", "source": msg["trigger"]}
            if msg["trigger"] == "webhook":
                condition["value"] = str(uuid.uuid4())
            changes["conditions"] = [{"condition": condition}]
    if "triggers" in msg or "trigger_values" in msg:
        current = [(c.get("condition") or {}).get("source") for c in rule.get("conditions") or []]
        changes["conditions"] = _conditions(
            msg.get("triggers") or list(dict.fromkeys(t for t in current if t)), rule.get("conditions"), msg.get("trigger_values")
        )
    if "schedule" in msg:
        try:
            changes["schedules"] = _schedule(coordinator, msg["schedule"])
        except HomeAssistantError as err:
            raise RuleError("bad_schedule", str(err)) from err
    if "also" in msg:
        changes["historyConditions"] = _also(msg["also"], rule.get("historyConditions"))
    if "devices" in msg or "scope" in msg or "zones" in msg:
        old_sources = rule.get("sources") or []
        scope = msg.get("scope") or (old_sources[0].get("type") if old_sources else "include")
        devices = msg["devices"] if "devices" in msg else [s.get("device") for s in old_sources]
        _check_devices(coordinator, devices)
        changes["sources"] = _sources(devices, scope, old_sources, msg.get("zones"))
    kinds = [a.get("type") for a in rule.get("actions") or []]
    if "actions" in msg:
        try:
            changes["actions"] = _actions(coordinator, msg["actions"], rule.get("actions"))
        except HomeAssistantError as err:
            raise RuleError("bad_action", str(err)) from err
    elif msg.get("action") == "light":
        if "light_device" not in msg:
            raise RuleError("no_device", "Pick the device whose light to turn on")
        _check_devices(coordinator, [msg["light_device"]])
        changes["actions"] = [_light_action(msg["light_device"], msg.get("light_seconds", 30))]
    elif msg.get("action") == "notify" and "SEND_NOTIFICATION" not in kinds:
        who = _my_receiver(coordinator)
        if who is None:
            raise RuleError("no_receiver", "Couldn't work out who to notify")
        changes["actions"] = [_notify_action(who, [c for c in ("push", "email") if msg.get(c)])]
    elif "push" in msg or "email" in msg:
        actions = [dict(a) for a in rule.get("actions") or []]
        found = False
        for action in actions:
            if action.get("type") != "SEND_NOTIFICATION":
                continue
            meta = dict(action.get("metadata") or {})
            receivers = [dict(r) for r in meta.get("receivers") or []]
            for rec in receivers:
                if rec.get("user") != rule.get("userId") and len(receivers) > 1:
                    continue
                channels = [c for c in rec.get("channels") or []]
                for name in ("push", "email"):
                    if name in msg:
                        channels = [c for c in channels if c != name] + ([name] if msg[name] else [])
                rec["channels"] = channels
                found = True
            meta["receivers"] = receivers
            action["metadata"] = meta
        if not found:
            raise RuleError("no_notify", "This rule has no notification to change")
        changes["actions"] = actions
    if "cooldown_enabled" in msg or "cooldown_minutes" in msg:
        cooldown = dict(rule.get("cooldown") or {})
        if "cooldown_enabled" in msg:
            cooldown["enable"] = msg["cooldown_enabled"]
        if "cooldown_minutes" in msg:
            cooldown["timeout"] = int(msg["cooldown_minutes"] * 60_000)
        cooldown.pop("lastExecutedAt", None)
        changes["cooldown"] = cooldown
    return changes


async def async_remove_entry(hass: HomeAssistant, entry: ProtectRulesConfigEntry) -> None:
    """Protect Rules was removed: forget the device names it kept."""
    await Store(hass, 1, DEVICE_STORE).async_remove()


async def async_unload_entry(hass: HomeAssistant, entry: ProtectRulesConfigEntry) -> bool:
    hass.services.async_remove(DOMAIN, "set_cooldown")
    unload_cards(hass, hass.data.pop(CARD_URLS, []))
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _conditions(
    triggers: list[str], old: list[dict[str, Any]] | None = None, values: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """One "is <trigger>" condition each (any of them fires the rule). A list
    of values gives one condition per value (this face, that face). A webhook
    the rule already had keeps its condition, so its trigger ID doesn't change."""
    have = {(c.get("condition") or {}).get("source"): c for c in old or []}
    out = []
    values = values or {}
    for trig in dict.fromkeys(triggers):
        val = values.get(trig)
        if isinstance(val, list):
            out.extend({"condition": {"type": "is", "source": trig, "value": v}} for v in dict.fromkeys(val))
        elif trig == "webhook":
            out.append(have.get(trig) or {"condition": {"type": "is", "source": trig, "value": str(uuid.uuid4())}})
        elif val is not None:
            out.append({"condition": {"type": "is", "source": trig, "value": val}})
        else:
            out.append({"condition": {"type": "is", "source": trig}})
    return out


def _schedule(coordinator: RulesCoordinator, spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Protect's rule schedules: one entry per day and time range, the way its
    own editor writes them. A block that runs past midnight is split in two."""
    if spec["mode"] == "always":
        return []
    if spec["mode"] == "predefined":
        found = next((s for s in coordinator.schedules if s["id"] == spec["id"]), None)
        if found is None:
            raise HomeAssistantError("That schedule no longer exists in Protect")
        return found["schedules"]

    def entry(day: int, start: list[int], end: list[int]) -> dict[str, Any]:
        return {
            "schedule": {
                "type": "is",
                "unit": "day_of_week",
                "values": [day],
                "and": {"type": "is", "unit": "time_range", "values": [list(start), list(end)]},
            }
        }

    out = []
    for block in spec["blocks"]:
        start, end = block["start"], block["end"]
        for day in sorted(set(block["days"])):
            if end > start:
                out.append(entry(day, start, end))
            else:  # through midnight: the evening, then the next morning
                out.append(entry(day, start, [23, 59]))
                if end != [0, 0]:
                    out.append(entry((day + 1) % 7, [0, 0], end))
    return out


def _also(groups: list[dict[str, Any]], old: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Protect's historyConditions: each step is a list of bare "is <trigger>"
    conditions (any of them counts) and the time allowed for it, in ms."""
    have = {c.get("source"): {"condition": c} for step in old or [] for c in step.get("conditions") or []}
    return [
        {
            "conditions": [c["condition"] for c in _conditions(group["triggers"], list(have.values()), group.get("trigger_values"))],
            "period": group["seconds"] * 1000,
        }
        for group in groups
    ]


def _check_devices(coordinator: RulesCoordinator, macs: list[str]) -> None:
    """Refuse to send Protect a device it no longer has (a rule can still
    name a camera that was removed; saving it again must not)."""
    coordinator.refresh_devices()
    try:
        coordinator.devices.check(macs)
    except ValueError as err:
        raise RuleError("removed_device", str(err)) from err


def _sources(
    devices: list[str],
    scope: str,
    old: list[dict[str, Any]] | None = None,
    zones: dict[str, dict[str, list[int]]] | None = None,
) -> list[dict[str, Any]]:
    """Device scope. A device already in the rule keeps its entry; where zones
    are given for a device they replace its zone / line / loiter picks."""
    have = {s.get("device"): s for s in old or []}
    out = []
    for mac in dict.fromkeys(devices):
        src = dict(have.get(mac) or {"device": mac})
        picked = {"line": [], "zone": [], "loiter": [], "package": [], **(src.get("zones") or {})}
        if zones is not None and mac in zones:
            for kind in ("zone", "line", "loiter"):
                picked[kind] = sorted(set(zones[mac].get(kind) or []))
        if scope == "exclude":
            picked = {**picked, "zone": [], "line": [], "loiter": []}  # zones only narrow an include
        out.append({**src, "zones": picked, "type": scope})
    return out


def _actions(coordinator: RulesCoordinator, specs: list[dict[str, Any]], old: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    old = old or []
    old_notify = next((a for a in old if a.get("type") == "SEND_NOTIFICATION"), None)
    out: list[dict[str, Any]] = []
    for spec in specs:
        kind = spec["kind"]
        if kind == "keep":
            if not 0 <= spec["index"] < len(old):
                raise HomeAssistantError("That action no longer exists")
            out.append(old[spec["index"]])
        elif kind == "notify":
            channels = [c for c in ("push", "email") if spec.get(c)]
            who = _my_receiver(coordinator)
            if old_notify is not None:
                # keep the other receivers and their settings; change only my channels
                action = {**old_notify, "metadata": dict(old_notify.get("metadata") or {})}
                receivers = [dict(r) for r in action["metadata"].get("receivers") or []]
                mine = [r for r in receivers if who and r.get("user") == who["user"]] or receivers[:1]
                if mine:
                    mine[0]["channels"] = channels
                elif who:
                    receivers.append({**who, "channels": channels, "schedules": []})
                action["metadata"]["receivers"] = receivers
                out.append(action)
            elif who is None:
                raise HomeAssistantError("Couldn't work out who to notify")
            else:
                out.append(_notify_action(who, channels))
        elif kind == "light":
            _check_devices(coordinator, [spec["device"]])
            out.append(_light_action(spec["device"], spec["seconds"]))
        elif kind == "ptz":
            _check_devices(coordinator, [spec["device"]])
            meta: dict[str, Any] = {"target": spec["device"], "mode": spec["mode"]}
            if spec["mode"] == "preset":
                if not spec.get("preset_id"):
                    raise HomeAssistantError("Pick a PTZ preset (save one on the camera in Protect first)")
                meta.update(presetId=spec["preset_id"], returnHome=spec["return_home"] * 1000)
            elif spec["mode"] == "patrol":
                if not spec.get("patrol_id"):
                    raise HomeAssistantError("Pick a PTZ patrol (set one up on the camera in Protect first)")
                meta.update(patrolId=spec["patrol_id"], repeat=spec["repeat"])
            else:
                # keep the tracking details (zoom, object types) an existing action already has
                prev = next(
                    (a.get("metadata") or {} for a in old if a.get("type") == "PTZ"
                     and (a.get("metadata") or {}).get("mode") == "autotrack"
                     and (a.get("metadata") or {}).get("target") == spec["device"]),
                    {},
                )
                meta.update({k: prev[k] for k in ("zoom", "objectTypes") if k in prev})
                meta["enable"] = spec["enable"]
            out.append({"type": "PTZ", "metadata": meta, "order": -1})
        elif kind == "webhook":
            out.append({"type": "HTTP_REQUEST", "metadata": {"url": spec["url"], "method": spec["method"]}, "order": -1})
    return out


def _notify_action(who: dict[str, Any], channels: list[str]) -> dict[str, Any]:
    return {
        "type": "SEND_NOTIFICATION",
        "metadata": {"receivers": [{**who, "channels": channels, "schedules": []}]},
        "order": -1,
    }


def _light_action(device: str, seconds: int) -> dict[str, Any]:
    return {
        "type": "SET_LIGHT",
        "metadata": {"enable": True, "sources": [{"type": "include", "device": device}], "duration": seconds * 1000},
        "order": -1,
    }


def _my_receiver(coordinator: RulesCoordinator) -> dict[str, Any] | None:
    """Who notifications go to: copied from an existing notify rule."""
    for rule in (coordinator.data or {}).values():
        for action in rule.get("actions") or []:
            if action.get("type") != "SEND_NOTIFICATION":
                continue
            for rec in (action.get("metadata") or {}).get("receivers") or []:
                if rec.get("user") == rule.get("userId"):
                    return {"user": rec["user"], "ucoreUser": rec.get("ucoreUser")}
    return None


@websocket_api.websocket_command(
    {
        vol.Required("type"): "protect_rules/create",
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=80)),
        vol.Optional("trigger"): TRIGGER,
        vol.Optional("devices", default=list): [MAC],
        vol.Optional("action"): vol.In(("notify", "light")),
        **RULE_FIELDS,
        vol.Optional("push", default=False): bool,
        vol.Optional("email", default=False): bool,
        vol.Optional("light_device"): vol.Match(r"^[0-9A-F]{12}$"),
        vol.Optional("light_seconds", default=30): vol.All(int, vol.Range(5, 3600)),
        vol.Optional("cooldown_enabled", default=False): bool,
        vol.Optional("cooldown_minutes", default=10): vol.All(vol.Coerce(float), vol.Range(0.5, 1440)),
        vol.Optional("enable", default=True): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_create(hass: HomeAssistant, connection, msg) -> None:
    """Create a rule in Protect's Alarm Manager."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_loaded", "Protect Rules isn't loaded")
        return
    triggers = msg.get("triggers") or ([msg["trigger"]] if "trigger" in msg else [])
    if not triggers:
        connection.send_error(msg["id"], "no_trigger", "Pick at least one trigger")
        return
    if "actions" in msg:
        try:
            actions = _actions(coordinator, msg["actions"])
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "bad_action", str(err))
            return
    elif msg.get("action") == "notify":
        who = _my_receiver(coordinator)
        if who is None:
            connection.send_error(msg["id"], "no_receiver", "Couldn't work out who to notify")
            return
        actions = [_notify_action(who, [c for c in ("push", "email") if msg[c]])]
    elif msg.get("action") == "light":
        if "light_device" not in msg:
            connection.send_error(msg["id"], "no_device", "Pick the device whose light to turn on")
            return
        try:
            _check_devices(coordinator, [msg["light_device"]])
        except RuleError as err:
            connection.send_error(msg["id"], err.code, str(err))
            return
        actions = [_light_action(msg["light_device"], msg["light_seconds"])]
    else:
        connection.send_error(msg["id"], "no_action", "Add at least one action")
        return
    try:
        schedules = _schedule(coordinator, msg["schedule"]) if "schedule" in msg else []
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "bad_schedule", str(err))
        return
    try:
        _check_devices(coordinator, msg["devices"])
    except RuleError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    rule = {
        "name": msg["name"].strip(),
        "enable": msg["enable"],
        "sources": _sources(msg["devices"], msg.get("scope", "include"), None, msg.get("zones")),
        "conditions": _conditions(triggers, None, msg.get("trigger_values")),
        "historyConditions": _also(msg.get("also") or []),
        "schedules": schedules,
        "actions": actions,
        "cooldown": {"enable": msg["cooldown_enabled"], "timeout": int(msg["cooldown_minutes"] * 60_000)},
    }
    try:
        created = await coordinator.async_create(rule)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "rejected", str(err))
        return
    connection.send_result(msg["id"], {"rule_id": created.get("id")})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "protect_rules/history",
        vol.Required("rule_id"): str,
        vol.Optional("limit", default=12): vol.All(int, vol.Range(1, 100)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_history(hass: HomeAssistant, connection, msg) -> None:
    """The last times a rule fired: when, which trigger, on which device and
    zone, and the detection it came from (if it was one)."""
    coordinator = _coordinator(hass)
    if coordinator is None or msg["rule_id"] not in (coordinator.data or {}):
        connection.send_error(msg["id"], "not_found", "No such rule")
        return
    try:
        rows = await coordinator.api.api_request(f"automations/{msg['rule_id']}/history?limit={msg['limit']}")
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "history_failed", f"Couldn't read the rule's history: {err}")
        return
    coordinator.refresh_devices()
    devices = coordinator.devices
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        trig = row.get("trigger") or {}
        # the device a past firing came from may have been removed since
        known = (coordinator.zones or {}).get(devices.ids.get(trig.get("device")), {})
        zones = []
        for kind, label in (("zone", "Zone"), ("line", "Line"), ("loiter", "Loiter zone"), ("package", "Package zone")):
            for zid in (trig.get("zones") or {}).get(kind) or []:
                name = next((z["name"] for z in known.get(kind, []) if z["id"] == zid), f"#{zid}")
                zones.append(f"{label}: {name}")
        src = trig.get("sourceEvent") or {}
        out.append(
            {
                "at": row.get("timestamp") or trig.get("timestamp"),
                "status": row.get("status"),
                "trigger": trig.get("key"),
                "device": devices.label_by_id(trig.get("device")),
                "zones": zones,
                "event_id": row.get("detectionEventId"),
                "event_type": src.get("type"),
                "score": src.get("score"),
            }
        )
    connection.send_result(msg["id"], {"history": out})


@websocket_api.websocket_command({vol.Required("type"): "protect_rules/delete", vol.Required("rule_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete(hass: HomeAssistant, connection, msg) -> None:
    """Delete a rule from Protect's Alarm Manager, and its HA entities."""
    coordinator = _coordinator(hass)
    if coordinator is None or msg["rule_id"] not in (coordinator.data or {}):
        connection.send_error(msg["id"], "not_found", "No such rule")
        return
    try:
        await coordinator.async_delete(msg["rule_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "rejected", str(err))
        return
    registry = er.async_get(hass)
    for ent in list(registry.entities.values()):
        if ent.platform == DOMAIN and ent.unique_id.endswith(f"_{msg['rule_id']}"):
            registry.async_remove(ent.entity_id)
    connection.send_result(msg["id"])
