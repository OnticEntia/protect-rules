"""Tests for the device and outage parts of logic.py: rules that name a
device Protect no longer has, and a console that briefly doesn't answer.

    python3 -m unittest discover -s tests
"""

import importlib.util
import pathlib
import sys
import unittest

sys.dont_write_bytecode = True
_PATH = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "protect_rules" / "logic.py"
_spec = importlib.util.spec_from_file_location("protect_rules_logic_devices", _PATH)
logic = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = logic
_spec.loader.exec_module(logic)

A, B, C = "AAAAAAAAAAAA", "BBBBBBBBBBBB", "CCCCCCCCCCCC"
NOW = [(A, "id-a", "Camera A", True), (B, "id-b", "Camera B", False)]


def rule(sources=(), actions=()):
    return {"id": "r", "name": "Rule", "sources": [{"device": m, "type": "include"} for m in sources], "actions": list(actions)}


def devices(now=NOW, before=None):
    d = logic.Devices()
    if before is not None:
        d.update(before)
    d.update(now)
    return d


class RuleDevices(unittest.TestCase):
    def test_scope_light_and_ptz(self):
        r = rule([A, B], [
            {"type": "SET_LIGHT", "metadata": {"sources": [{"device": C}]}},
            {"type": "PTZ", "metadata": {"target": A}},
            {"type": "SEND_NOTIFICATION", "metadata": {"receivers": []}},
        ])
        self.assertEqual(logic.rule_devices(r), [A, B, C])

    def test_odd_shapes_do_not_break_it(self):
        r = {"sources": [None, {}, {"device": None}, {"device": 5}, {"device": A}], "actions": [None, {"metadata": None}, {"metadata": {"sources": [None]}}]}
        self.assertEqual(logic.rule_devices(r), [A])
        self.assertEqual(logic.rule_devices({}), [])


class Labels(unittest.TestCase):
    def test_present_offline_removed(self):
        d = devices(before=NOW + [(C, "id-c", "Camera C", True)])
        self.assertEqual(d.label(A), "Camera A")
        self.assertEqual(d.label(B), "Camera B")  # offline is still in Protect
        self.assertIn(B, d.offline)
        self.assertFalse(d.is_removed(B))
        self.assertTrue(d.is_removed(C))
        self.assertEqual(d.label(C), "Camera C (removed)")
        self.assertEqual(d.label_by_id("id-c"), "Camera C (removed)")
        self.assertEqual(d.label_by_id("id-a"), "Camera A")

    def test_removed_and_never_seen_is_named_not_an_id(self):
        d = devices()
        self.assertEqual(d.label(C), logic.REMOVED_NAME)
        self.assertEqual(d.label_by_id("id-zzz"), logic.REMOVED_NAME)
        self.assertIsNone(d.label(None))
        self.assertIsNone(d.label_by_id(None))

    def test_unknown_device_list_calls_nothing_removed(self):
        d = devices()
        d.update(None)
        self.assertFalse(d.known)
        self.assertFalse(d.is_removed(A))
        self.assertEqual(d.label(A), "Camera A")  # remembered
        self.assertEqual(d.removed_in({"r": rule([A, C])}), {})
        d.check([A, C])  # not refused: we can't tell
        d.update([])
        self.assertFalse(d.known)

    def test_names_survive_a_restart(self):
        first = devices(before=NOW + [(C, "id-c", "Camera C", True)])
        again = logic.Devices(first.remembered)
        again.update(NOW)
        self.assertEqual(again.label(C), "Camera C (removed)")

    def test_rename_is_remembered(self):
        d = devices()
        _, learned = d.update([(A, "id-a", "Front", True), (B, "id-b", "Camera B", True)])
        self.assertTrue(learned)
        d.update([(B, "id-b", "Camera B", True)])
        self.assertEqual(d.label(A), "Front (removed)")

    def test_remembered_names_are_capped(self):
        d = logic.Devices()
        d.update([(f"{i:012X}", "", f"Cam {i}", True) for i in range(logic.REMEMBER_MAX + 50)])
        self.assertEqual(len(d.remembered), logic.REMEMBER_MAX)


class Changes(unittest.TestCase):
    def test_added_and_removed_devices_are_noticed(self):
        d = logic.Devices()
        self.assertEqual(d.update(NOW)[0], False)  # the first list is not a change
        self.assertEqual(d.update(NOW)[0], False)
        self.assertEqual(d.update(NOW + [(C, "id-c", "Camera C", True)])[0], True)  # adopted
        self.assertEqual(d.update(NOW)[0], True)  # removed
        self.assertEqual(d.update([(A, "id-a", "Camera A", False), NOW[1]])[0], False)  # only went offline


class RemovedIn(unittest.TestCase):
    def test_lists_removed_devices_rules_name(self):
        d = devices(before=NOW + [(C, "id-c", "Camera C", True)])
        rules = {"1": rule([A, C]), "2": rule([], [{"type": "PTZ", "metadata": {"target": "DDDDDDDDDDDD"}}])}
        self.assertEqual(d.removed_in(rules), {C: "Camera C", "DDDDDDDDDDDD": None})


class Check(unittest.TestCase):
    def test_present_and_offline_devices_pass(self):
        devices().check([A, B])
        devices().check([])
        devices().check(None)

    def test_removed_device_refused_by_name(self):
        d = devices(before=NOW + [(C, "id-c", "Camera C", True)])
        with self.assertRaises(ValueError) as ctx:
            d.check([A, C])
        self.assertIn("Camera C was removed from Protect", str(ctx.exception))
        self.assertNotIn(C, str(ctx.exception))

    def test_never_seen_device_refused_without_showing_an_id(self):
        with self.assertRaises(ValueError) as ctx:
            devices().check([C, "DDDDDDDDDDDD"])
        self.assertIn("were removed", str(ctx.exception))
        self.assertNotIn(C, str(ctx.exception))


class Summary(unittest.TestCase):
    def test_attributes_stay_lists_of_strings(self):
        d = devices(before=NOW + [(C, "id-c", "Camera C", True)])
        s = logic.rule_device_summary(rule([A, B, C, "DDDDDDDDDDDD"]), d)
        self.assertEqual(s["devices"], ["Camera A", "Camera B", "Camera C (removed)", logic.REMOVED_NAME])
        self.assertEqual(s["removed_devices"], ["Camera C (removed)", logic.REMOVED_NAME])
        self.assertEqual(s["offline_devices"], ["Camera B"])
        for value in s.values():
            self.assertTrue(all(isinstance(x, str) for x in value))

    def test_rule_without_devices(self):
        self.assertEqual(logic.rule_device_summary(rule(), devices()), {"devices": [], "removed_devices": [], "offline_devices": []})


class Outages(unittest.TestCase):
    def test_short_outage_is_one_warning_and_keeps_the_rules(self):
        o = logic.Outage(grace=3)
        self.assertEqual([o.failed(True) for _ in range(3)], ["warn", "quiet", "quiet"])
        self.assertEqual(o.succeeded(), 3)
        self.assertEqual(o.succeeded(), 0)
        self.assertEqual(o.failed(True), "warn")  # a new outage warns again

    def test_long_outage_fails(self):
        o = logic.Outage(grace=2)
        self.assertEqual([o.failed(True) for _ in range(4)], ["warn", "quiet", "fail", "fail"])

    def test_nothing_to_keep_fails_at_once(self):
        self.assertEqual(logic.Outage().failed(False), "fail")


if __name__ == "__main__":
    unittest.main()
