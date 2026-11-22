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
