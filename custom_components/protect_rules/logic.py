"""The parts of Protect Rules that need no Home Assistant: checking what
Protect sent, deciding when a rule is really gone, when it fired, and whether
it changed. Kept free of HA imports so tests/ can load it by file path.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# a rule has to be missing from this many good reads in a row before its
# entities are removed (one odd answer from Protect must not delete them)
PRUNE_AFTER = 3
# how far a history row's time may be from the firing it is said to describe
HISTORY_TOLERANCE_MS = 30_000
# the parts of a rule the editor can change; a rule "changed" when these did
EDITED_FIELDS = ("name", "enable", "sources", "conditions", "historyConditions", "schedules", "actions", "cooldown")


def parse_rules(payload: Any) -> dict[str, dict[str, Any]]:
    """{rule_id: rule} from Protect's rule list. Raises ValueError when the
    answer doesn't look like a rule list, so it is never acted on."""
    if not isinstance(payload, list):
        raise ValueError(f"expected a list of rules, got {type(payload).__name__}")
    out: dict[str, dict[str, Any]] = {}
    for rule in payload:
        if not isinstance(rule, dict):
            raise ValueError("a rule that isn't an object")
        if not isinstance(rule.get("id"), str) or not rule["id"]:
            raise ValueError("a rule without an id")
        if not isinstance(rule.get("name"), str):
            raise ValueError(f"rule {rule['id']} has no name")
        if not rule.get("deleted"):
            out[rule["id"]] = rule
    return out


def last_fired(rule: dict[str, Any] | None) -> float:
    """When the rule last fired (ms), 0 if never or unknown."""
    value = ((rule or {}).get("status") or {}).get("lastExecutedAt")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def merge_rules(
    old: dict[str, dict[str, Any]] | None,
    new: dict[str, dict[str, Any]],
    misses: dict[str, int],
    limit: int = PRUNE_AFTER,
) -> dict[str, dict[str, Any]]:
    """The rules after a good read. A rule the read left out is kept (as it
    was) until it has been missing `limit` reads in a row; `misses` carries
    the count between reads. A rule whose status is older than what the live
    stream already showed keeps the newer status."""
    old = old or {}
    out: dict[str, dict[str, Any]] = {}
    for rule_id, rule in new.items():
        misses.pop(rule_id, None)
        prev = old.get(rule_id)
        if prev is not None and last_fired(prev) > last_fired(rule):
            rule = {**rule, "status": prev.get("status")}
        out[rule_id] = rule
    for rule_id, rule in old.items():
        if rule_id in new:
            continue
        misses[rule_id] = misses.get(rule_id, 0) + 1
        if misses[rule_id] < limit:
            out[rule_id] = rule
        else:
            del misses[rule_id]
    return out


class FireTracker:
    """Remembers when each rule last fired, so a firing is reported once
    whether the live stream or a poll showed it first."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def baseline(self, rules: dict[str, dict[str, Any]]) -> None:
        """Take note of rules not seen before without reporting them."""
        for rule_id, rule in rules.items():
            self._last.setdefault(rule_id, last_fired(rule))

    def observe(self, rule_id: str, fired_at: Any) -> bool:
        """True if this is a firing newer than any seen for a known rule."""
        if not isinstance(fired_at, (int, float)) or isinstance(fired_at, bool) or fired_at <= 0:
            return False
        prev = self._last.get(rule_id)
        if prev is None or fired_at <= prev:
            return False
        self._last[rule_id] = fired_at
        return True

    def poll_fires(self, rules: dict[str, dict[str, Any]]) -> list[tuple[str, float]]:
        """The firings a fresh rule list shows that weren't reported yet."""
        fired = []
        for rule_id, rule in rules.items():
            if rule_id not in self._last:
                self._last[rule_id] = last_fired(rule)
            elif self.observe(rule_id, last_fired(rule)):
                fired.append((rule_id, last_fired(rule)))
        for rule_id in [r for r in self._last if r not in rules]:
            del self._last[rule_id]
        return fired


def match_history_row(rows: Any, fired_at: float, tolerance: float = HISTORY_TOLERANCE_MS) -> dict[str, Any] | None:
    """The history row for the firing at `fired_at`: the one closest in time,
    if it is close enough. None rather than some other firing's row."""
    best: tuple[float, dict[str, Any]] | None = None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        at = row.get("timestamp") or (row.get("trigger") or {}).get("timestamp")
        if not isinstance(at, (int, float)) or isinstance(at, bool):
            continue
        gap = abs(at - fired_at)
        if gap <= tolerance and (best is None or gap < best[0]):
            best = (gap, row)
    return best[1] if best else None


def fingerprint(rule: dict[str, Any]) -> str:
    """Changes when anything the editor can change does; not when the rule
    merely fires."""
    core = {key: rule.get(key) for key in EDITED_FIELDS}
    if isinstance(core["cooldown"], dict):
        core["cooldown"] = {k: v for k, v in core["cooldown"].items() if k != "lastExecutedAt"}
    return hashlib.sha1(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- devices
# A rule names devices by MAC (its scope, a light to turn on, a PTZ camera).
# A device can be offline (still in Protect) or removed (no longer in
# Protect); a rule can go on naming a removed one.

REMOVED_NAME = "Removed device"
REMEMBER_MAX = 500  # names of devices seen, kept so a removed one can still be named


def rule_devices(rule: dict[str, Any]) -> list[str]:
    """Every device (MAC) a rule names, in order, once each."""
    out: list[str] = []

    def add(mac: Any) -> None:
        if isinstance(mac, str) and mac and mac not in out:
            out.append(mac)

    for src in rule.get("sources") or []:
        if isinstance(src, dict):
            add(src.get("device"))
    for action in rule.get("actions") or []:
        meta = action.get("metadata") if isinstance(action, dict) else None
        if not isinstance(meta, dict):
            continue
        add(meta.get("target"))
        for src in meta.get("sources") or []:
            if isinstance(src, dict):
                add(src.get("device"))
    return out


class Devices:
    """What Protect has right now, plus the names of devices seen before.

    names: {mac: name} of the devices in Protect; ids: {protect id: mac};
    offline: MACs in Protect but not connected. known is False when the
    device list couldn't be read (or came back empty): then nothing is
    called removed, since we can't tell.
    remembered: {mac or protect id: name} of every device seen, so one that
    is removed later can still be named.
    """

    def __init__(self, remembered: dict[str, str] | None = None) -> None:
        self.names: dict[str, str] = {}
        self.ids: dict[str, str] = {}
        self.offline: set[str] = set()
        self.known = False
        self.remembered: dict[str, str] = dict(remembered or {})

    def update(self, devices: list[tuple[str, str, str, bool]] | None) -> tuple[bool, bool]:
        """Take the current device list: (mac, protect id, name, connected)
        each, or None if it couldn't be read. Returns (the set of devices
        changed, a name to remember changed)."""
        if not devices:
            self.known = False
            return False, False
        names = {mac: name or mac for mac, _, name, _ in devices if mac}
        changed = self.known and set(names) != set(self.names)
        self.names = names
        self.ids = {dev_id: mac for mac, dev_id, _, _ in devices if mac and dev_id}
        self.offline = {mac for mac, _, _, connected in devices if mac and not connected}
        self.known = True
        learned = False
        for mac, dev_id, name, _ in devices:
            for key in (mac, dev_id):
                if key and name and self.remembered.get(key) != name:
                    self.remembered.pop(key, None)  # re-added below: newest last
                    self.remembered[key] = name
                    learned = True
        while len(self.remembered) > REMEMBER_MAX:
            self.remembered.pop(next(iter(self.remembered)))
        return changed, learned

    def is_removed(self, mac: str) -> bool:
        return self.known and mac not in self.names

    def label(self, mac: str | None) -> str | None:
        """A name for a device a rule names: its name, "<name> (removed)",
        or "Removed device" when it was never seen. Never blank or an id,
        unless the device list is unknown and so is the device."""
        if not mac:
            return None
        if mac in self.names:
            return self.names[mac]
        if not self.known:
            return self.remembered.get(mac) or mac
        return f"{self.remembered[mac]} (removed)" if mac in self.remembered else REMOVED_NAME

    def label_by_id(self, dev_id: str | None) -> str | None:
        """The same for a Protect device id (what a rule's history uses)."""
        if not dev_id:
            return None
        if dev_id in self.ids:
            return self.names.get(self.ids[dev_id])
        if not self.known:
            return self.remembered.get(dev_id)
        return f"{self.remembered[dev_id]} (removed)" if dev_id in self.remembered else REMOVED_NAME

    def removed_in(self, rules: dict[str, dict[str, Any]]) -> dict[str, str | None]:
        """{mac: last known name or None} of removed devices the rules name."""
        if not self.known:
            return {}
        return {
            mac: self.remembered.get(mac)
            for rule in rules.values()
            for mac in rule_devices(rule)
            if mac not in self.names
        }

    def check(self, macs: Any) -> None:
        """Refuse (ValueError, with a message for the user) to send Protect a
        device it no longer has."""
        if not self.known:
            return
        gone = [mac for mac in dict.fromkeys(macs or []) if mac not in self.names]
        if not gone:
            return
        names = ", ".join(self.remembered.get(mac) or "a device" for mac in gone)
        raise ValueError(
            f"{names} {'was' if len(gone) == 1 else 'were'} removed from Protect. "
            "Take it out of the rule (its devices and actions), then save again."
        )


def rule_device_summary(rule: dict[str, Any], devices: Devices) -> dict[str, Any]:
    """For a rule's entity attributes: the devices it names, by name, and
    which of those are gone or offline. Always lists of strings."""
    macs = rule_devices(rule)
    return {
        "devices": [devices.label(mac) or REMOVED_NAME for mac in macs],
        "removed_devices": [devices.label(mac) or REMOVED_NAME for mac in macs if devices.is_removed(mac)],
        "offline_devices": [devices.names[mac] for mac in macs if mac in devices.offline and mac in devices.names],
    }


# ----------------------------------------------------------------- outages

OUTAGE_GRACE = 3  # failed reads in a row that are ridden out with the last known rules


class Outage:
    """How to treat a failed read of the rules. A short outage (the console
    restarting, a timeout) is ridden out: the first failure is worth one
    warning, the next ones nothing, and the rules stay as they were. Only
    when it lasts is it reported as a failure (entities go unavailable)."""

    def __init__(self, grace: int = OUTAGE_GRACE) -> None:
        self.grace = grace
        self.failures = 0

    def failed(self, have_data: bool) -> str:
        """"warn", "quiet" (keep the last rules) or "fail" (give up for now)."""
        self.failures += 1
        if not have_data or self.failures > self.grace:
            return "fail"
        return "warn" if self.failures == 1 else "quiet"

    def succeeded(self) -> int:
        """Failed reads this success ends (0 if there was no outage)."""
        failures, self.failures = self.failures, 0
        return failures
