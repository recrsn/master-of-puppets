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


if __name__ == "__main__":
    unittest.main()
