"""round: a section that fails or times out is named again at the end, so a long round cannot hide it.
Run: python3 -I skills/master-of-puppets/tests/test_round.py
Runs in its own empty MACHINE_LEASE_DIR; nothing calls GitHub or sends a message."""
import importlib
import io
import os
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


class Round(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = self.tmp.name
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.c = importlib.import_module("coordinator")
        self.m.RUN.env = {"MOP_ACTOR": "a"}
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "a", "prs": [], "tool": "claude"}
        self.m.save_roster(roster)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def test_a_failed_prs_section_is_named_at_the_end(self):
        def prs(*a):
            raise SystemExit(3)
        self.c.round_prs = prs
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.c.main(["round"])
        self.assertEqual(code, 1)
        last = out.getvalue().strip().splitlines()[-1]
        self.assertTrue(last.startswith("ROUND INCOMPLETE — not checked: prs (exit 3)"), last)


    def test_active_only_leaves_paused_members_out(self):
        roster = self.m.load_roster()
        old = "2026-01-01T00:00:00+00:00"
        roster["members"]["a"] = [{"name": "p", "status": "paused", "updatedAt": old, "task": "parked"},
                                  {"name": "w", "status": "active", "updatedAt": old, "task": "working"}]
        self.m.save_roster(roster)
        out = io.StringIO()
        with redirect_stdout(out):
            self.c.round_stale(30, None, "a")
        text = out.getvalue()
        self.assertIn("w active", text)
        self.assertNotIn("p paused", text)
        self.assertIn("1 lines of paused members not shown", text)
        out = io.StringIO()
        with redirect_stdout(out):
            self.c.round_stale(30)
        self.assertIn("p paused", out.getvalue())  # without the flag, nothing is hidden

if __name__ == "__main__":
    unittest.main()
