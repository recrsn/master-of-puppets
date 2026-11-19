"""A scout's per-tick state is separate from its daily summary.
Run: python3 -I skills/master-of-puppets/tests/test_scout_state.py
Each test runs in its own empty MACHINE_LEASE_DIR; nothing touches the live state or sends a message."""
import importlib
import io
import os
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


class ScoutState(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # the helpers read JSON with open() and no close
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = os.path.join(self.tmp.name, "state")
        os.makedirs(os.environ["MACHINE_LEASE_DIR"])
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "puppet"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.p = importlib.import_module("puppet")
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": []}
        roster["members"]["a"] = [{"name": "sc", "role": "scout", "status": "active", "tickMin": 15}]
        self.m.save_roster(roster)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def tick(self, *extra):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.p.main(["scout", "tick", "--coordinator", "a", "--name", "sc", *extra]), 0)
        return self.m.scout_state("sc")

    def test_tick_state_replaces_itself_and_keeps_the_daily_summary(self):
        daily = self.tick("--summary", "day: 3 alerts, all resolved", "--state", "cursor 100")["summary"]
        st = self.tick("--state", "cursor 200")
        self.assertEqual(st["summary"], daily)
        self.assertEqual(st["state"]["text"], "cursor 200")
        st = self.tick()  # a tick with no state keeps the last one, with its own time
        self.assertEqual(st["state"]["text"], "cursor 200")
        self.assertEqual(st["summary"], daily)

    def scout(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.p.main(["scout", *argv[:1], "--coordinator", "a", "--name", "sc", *argv[1:]]), 0)
        return out.getvalue()

    def age(self, **fields):
        """Move times in the state file back by the given minutes."""
        st = self.m.scout_state("sc")
        back = lambda iso, mins: (self.m.dt.datetime.fromisoformat(iso) - self.m.dt.timedelta(minutes=mins)).isoformat()
        if "tick" in fields:
            st["lastTick"] = back(st["lastTick"], fields["tick"])
        if "seen" in fields:
            for a in st["openAlerts"]:
                a["lastSeen"] = back(a["lastSeen"], fields["seen"])
        if "resolved" in fields:
            st["resolved"] = {f: back(t, fields["resolved"]) for f, t in st.get("resolved", {}).items()}
        self.m.write_json(self.m.scout_path("sc"), st)

    def test_a_late_tick_says_so_and_names_the_cursor(self):
        self.scout("tick", "--state", "cursor 100")
        self.assertNotIn("LATE", self.scout("tick"))
        self.age(tick=45)
        out = self.scout("tick", "--state", "cursor 300")  # the new cursor must not hide the old one
        self.assertIn("LATE 45m", out)
        self.assertIn("cursor then was: cursor 100", out)
        self.assertNotIn("LATE", self.scout("tick"))

    def test_a_late_tick_that_starts_with_an_alert_still_says_late(self):
        self.scout("tick", "--state", "cursor 100")
        self.age(tick=45)
        self.assertNotIn("LATE", self.scout("alert", "--fingerprint", "f1", "--severity", "P2", "--text", "x"))
        self.assertIn("LATE 45m", self.scout("tick"))

    def test_an_alert_resolved_two_ticks_ago_reopens_as_a_flap(self):
        alert = ("alert", "--fingerprint", "f1", "--severity", "P2", "--text", "x")
        self.assertIn("NEW", self.scout(*alert))
        self.assertIn("RESOLVED", self.scout("resolve", "--fingerprint", "f1"))
        self.assertIn("REOPENED", self.scout(*alert))
        self.scout("resolve", "--fingerprint", "f1")
        self.age(resolved=61)  # more than 4 tick lengths of 15 min: a new alert again
        self.assertIn("NEW", self.scout(*alert))

    def test_a_tick_lists_alerts_not_seen_for_a_day(self):
        self.scout("alert", "--fingerprint", "old", "--severity", "P2", "--text", "x")
        self.assertNotIn("24 h", self.scout("tick"))
        self.age(seen=25 * 60)
        self.assertIn("not seen for 24 h, check each one again or resolve it: old", self.scout("tick"))


if __name__ == "__main__":
    unittest.main()
