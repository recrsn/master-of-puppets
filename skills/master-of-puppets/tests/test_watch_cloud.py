"""watch_cloud keeps the last state of each cloud task, so a restarted watch prints only changes.
Run: python3 -I skills/master-of-puppets/tests/test_watch_cloud.py
Runs in its own empty MACHINE_LEASE_DIR; no cloud task is read."""
import importlib
import io
import os
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


class Stop(Exception):
    pass


class WatchCloud(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = self.tmp.name
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator"):
            sys.modules.pop(name, None)
        self.c = importlib.import_module("coordinator")
        self.state = {"t1": "running", "t2": "done"}
        self.c.cloud_state = lambda tid: self.state[tid]
        self.c.nap = lambda s: (_ for _ in ()).throw(Stop())
        self.path = os.path.join(self.tmp.name, "cloud-a.txt")
        with open(self.path, "w") as f:
            f.write("t1 w1\nt2 w2\n")

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def cycle(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(Stop):
            self.c.watch_cloud(self.path, 1)
        return [x for x in out.getvalue().splitlines() if x]

    def test_a_restart_prints_only_changes(self):
        self.assertEqual(len(self.cycle()), 2)
        self.assertEqual(self.cycle(), [])  # a new watch: nothing changed
        self.state["t1"] = "done"
        self.assertEqual(self.cycle(), ["CLOUD t1 w1 done"])


if __name__ == "__main__":
    unittest.main()
