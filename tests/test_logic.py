"""Tests for custom_components/protect_rules/logic.py (no Home Assistant needed).

    python3 -m unittest discover -s tests
"""

import importlib.util
import pathlib
import sys
import unittest

sys.dont_write_bytecode = True
_PATH = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "protect_rules" / "logic.py"
_spec = importlib.util.spec_from_file_location("protect_rules_logic", _PATH)
logic = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = logic
_spec.loader.exec_module(logic)


def rule(rule_id, fired=None, **extra):
    return {"id": rule_id, "name": f"Rule {rule_id}", "enable": True, "status": {"lastExecutedAt": fired, "total": 1}, **extra}


class ParseRules(unittest.TestCase):
    def test_good_list(self):
        self.assertEqual(list(logic.parse_rules([rule("a"), rule("b")])), ["a", "b"])

    def test_empty_list_is_valid(self):
        self.assertEqual(logic.parse_rules([]), {})

    def test_deleted_rules_left_out(self):
        self.assertEqual(list(logic.parse_rules([rule("a", deleted=True), rule("b")])), ["b"])

    def test_bad_shapes_rejected(self):
        for bad in (None, {"error": "x"}, "nope", [None], ["a"], [{"name": "x"}], [{"id": 5, "name": "x"}], [{"id": "", "name": "x"}], [{"id": "a"}]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                logic.parse_rules(bad)


class MergeRules(unittest.TestCase):
    def test_missing_rule_kept_until_limit(self):
        misses = {}
        data = {"a": rule("a"), "b": rule("b")}
        only_a = {"a": rule("a")}
        data = logic.merge_rules(data, only_a, misses, limit=3)
        self.assertIn("b", data)
        data = logic.merge_rules(data, only_a, misses, limit=3)
        self.assertIn("b", data)
        data = logic.merge_rules(data, only_a, misses, limit=3)
        self.assertNotIn("b", data)
        self.assertEqual(misses, {})

    def test_reappearing_rule_resets_the_count(self):
        misses = {}
        data = {"a": rule("a"), "b": rule("b")}
        data = logic.merge_rules(data, {"a": rule("a")}, misses, limit=3)
        data = logic.merge_rules(data, {"a": rule("a")}, misses, limit=3)
        data = logic.merge_rules(data, {"a": rule("a"), "b": rule("b")}, misses, limit=3)
        self.assertEqual(misses, {})
        data = logic.merge_rules(data, {"a": rule("a")}, misses, limit=3)
        data = logic.merge_rules(data, {"a": rule("a")}, misses, limit=3)
        self.assertIn("b", data)

    def test_empty_read_does_not_drop_everything_at_once(self):
        misses = {}
        data = logic.merge_rules({"a": rule("a"), "b": rule("b")}, {}, misses)
        self.assertEqual(set(data), {"a", "b"})

    def test_new_rule_added_and_first_read(self):
        self.assertEqual(set(logic.merge_rules(None, {"a": rule("a")}, {})), {"a"})
        self.assertEqual(set(logic.merge_rules({"a": rule("a")}, {"a": rule("a"), "c": rule("c")}, {})), {"a", "c"})

    def test_older_status_from_a_poll_does_not_replace_newer(self):
        old = {"a": rule("a", fired=2000)}
        merged = logic.merge_rules(old, {"a": rule("a", fired=1000, name="Renamed")}, {})
        self.assertEqual(merged["a"]["status"]["lastExecutedAt"], 2000)
        self.assertEqual(merged["a"]["name"], "Renamed")
        merged = logic.merge_rules(old, {"a": rule("a", fired=3000)}, {})
        self.assertEqual(merged["a"]["status"]["lastExecutedAt"], 3000)


class Fires(unittest.TestCase):
    def test_baseline_reports_nothing(self):
        t = logic.FireTracker()
        t.baseline({"a": rule("a", fired=1000)})
        self.assertEqual(t.poll_fires({"a": rule("a", fired=1000)}), [])

    def test_stream_then_poll_reports_once(self):
        t = logic.FireTracker()
        t.baseline({"a": rule("a", fired=1000)})
        self.assertTrue(t.observe("a", 2000))
        self.assertFalse(t.observe("a", 2000))
        self.assertEqual(t.poll_fires({"a": rule("a", fired=2000)}), [])

    def test_poll_first_then_stream_reports_once(self):
        t = logic.FireTracker()
        t.baseline({"a": rule("a", fired=1000)})
        self.assertEqual(t.poll_fires({"a": rule("a", fired=2000)}), [("a", 2000)])
        self.assertFalse(t.observe("a", 2000))

    def test_first_ever_firing(self):
        t = logic.FireTracker()
        t.baseline({"a": rule("a")})
        self.assertTrue(t.observe("a", 500))

    def test_older_or_bad_values_ignored(self):
        t = logic.FireTracker()
        t.baseline({"a": rule("a", fired=1000)})
        for bad in (999, 1000, 0, None, "2000", True):
            self.assertFalse(t.observe("a", bad))

    def test_unknown_rule_not_reported(self):
        t = logic.FireTracker()
        self.assertFalse(t.observe("zzz", 5000))

    def test_new_rule_in_poll_is_a_baseline_and_gone_rules_forgotten(self):
        t = logic.FireTracker()
        t.baseline({"a": rule("a", fired=1000)})
        self.assertEqual(t.poll_fires({"b": rule("b", fired=9000)}), [])
        self.assertFalse(t.observe("a", 2000))  # forgotten
        self.assertTrue(t.observe("b", 9500))


class History(unittest.TestCase):
    def test_closest_row_within_tolerance(self):
        rows = [{"timestamp": 50_000, "n": 1}, {"timestamp": 41_000, "n": 2}, {"trigger": {"timestamp": 40_100}, "n": 3}]
        self.assertEqual(logic.match_history_row(rows, 40_000)["n"], 3)

    def test_no_row_close_enough(self):
        self.assertIsNone(logic.match_history_row([{"timestamp": 1_000}], 100_000))

    def test_odd_answers(self):
        for rows in (None, {}, "x", [None, "x", {"timestamp": "soon"}]):
            self.assertIsNone(logic.match_history_row(rows, 1000))


class Fingerprint(unittest.TestCase):
    def test_firing_does_not_change_it(self):
        a = rule("a", fired=1, cooldown={"enable": True, "timeout": 60000, "lastExecutedAt": 1})
        b = rule("a", fired=2, cooldown={"timeout": 60000, "enable": True, "lastExecutedAt": 2})
        self.assertEqual(logic.fingerprint(a), logic.fingerprint(b))

    def test_edits_change_it(self):
        base = rule("a", cooldown={"enable": True, "timeout": 60000}, actions=[{"type": "SET_LIGHT"}])
        for change in ({"name": "x"}, {"enable": False}, {"cooldown": {"enable": False, "timeout": 60000}}, {"actions": []}, {"sources": [{"device": "AA"}]}):
            with self.subTest(change=change):
                self.assertNotEqual(logic.fingerprint(base), logic.fingerprint({**base, **change}))


if __name__ == "__main__":
    unittest.main()
