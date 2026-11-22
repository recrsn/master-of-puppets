"""await-grant prints QUEUED with the position each time it changes, so a member never reads the lease file by hand.
Run: python3 -I skills/master-of-puppets/tests/test_await_position.py
Runs in its own empty MACHINE_LEASE_DIR; no server and no lease command run."""
import importlib
import io
import os
import sys
import tempfile
import types
import unittest
import warnings
from contextlib import redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
CLASS = "BUILD"


class AwaitPosition(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = self.tmp.name
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "puppet"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.p = importlib.import_module("puppet")
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {CLASS: dict(self.m.DEFAULT_REGISTRY[CLASS])}})
        self.edit(lambda st: st["queue"][CLASS].extend(self.entry(i) for i in ("x-1", "x-2", "me-1")))

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def entry(self, i):
        return {"coordinator": "a", "holder": i, "id": i, "priority": 0, "since": self.m.now().isoformat(),
                "minutes": 5, "gib": 1, "cpus": 0, "commands": "make"}

    def edit(self, fn):
        self.m.lock()
        try:
            st = self.m.load()
            fn(st)
            self.m.save(st, self.m.load_machine())
        finally:
            self.m.unlock()

    def test_position_changes_are_printed_once_each(self):
        steps = [lambda st: None,  # no change: no second QUEUED line
                 lambda st: st["queue"][CLASS].pop(0),
                 lambda st: st[CLASS].append(st["queue"][CLASS].pop(1))]
        self.p.nap = lambda s: self.edit(steps.pop(0))
        args = types.SimpleNamespace(cls=CLASS, id="me-1", timeout_min=30, appear_timeout=600, interval=0)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.p.await_grant(args), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[:2], ["QUEUED BUILD me-1: position 3 of 3 (next ahead: x-2); keep waiting",
                                     "QUEUED BUILD me-1: position 2 of 2 (next ahead: x-2); keep waiting"])
        self.assertEqual(lines[2], "GRANTED BUILD me-1")


    def test_release_withdraws_a_request_not_granted_yet(self):
        args = types.SimpleNamespace(cls=CLASS, id="me-1", peak_gib=None, peak_cpus=None, retire_vm=None,
                                     result="pass", note=None)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.p.release(args), 0)
        self.assertIn("WITHDRAWN BUILD me-1", out.getvalue())
        self.assertEqual([q["id"] for q in self.m.load()["queue"][CLASS]], ["x-1", "x-2"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.p.release(args), 3)  # neither held nor queued

if __name__ == "__main__":
    unittest.main()
