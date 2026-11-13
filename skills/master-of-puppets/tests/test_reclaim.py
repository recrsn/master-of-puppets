"""The server reclaims an expired lease once its grace period is over and its worktree has no process left.
Run: python3 -I skills/master-of-puppets/tests/test_reclaim.py
Each test runs in its own empty MACHINE_LEASE_DIR; nothing touches the live state."""
import datetime as dt
import importlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import warnings

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
CLASS = "BUILD"


class Reclaim(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # the helpers read JSON with open() and no close
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = os.path.join(self.tmp.name, "state")
        os.makedirs(os.environ["MACHINE_LEASE_DIR"])
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator", "puppet"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.c = importlib.import_module("coordinator")
        self.m.RUN.env = {"MOP_ACTOR": "test"}
        self.c.host_check = lambda: (True, "CALM")
        self.c.subprocess = types.SimpleNamespace(Popen=lambda *a, **k: types.SimpleNamespace(pid=0), DEVNULL=None,
                                                  STDOUT=None, run=self.c.subprocess.run)
        self.config(reclaim=None)
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": []}
        self.m.save_roster(roster)
        self.tree = os.path.join(self.tmp.name, "wt")
        os.makedirs(self.tree)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def config(self, reclaim):
        spec = {**self.m.DEFAULT_REGISTRY[CLASS], "autoAcquire": True}
        if reclaim is not None:
            spec["reclaimMinutes"] = reclaim
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {CLASS: spec}})

    def hold(self, entry_id, expired_minutes_ago):
        t = self.m.now()
        self.m.lock()
        try:
            state = self.m.load()
            state[CLASS].append({"coordinator": "a", "holder": "builder run", "id": entry_id, "worktree": self.tree,
                                 "project": self.m.project_key(self.tree)[0], "gib": 1, "cpus": 1, "commands": "make",
                                 "grantedAt": (t - dt.timedelta(minutes=expired_minutes_ago + 20)).isoformat(),
                                 "expiresAt": (t - dt.timedelta(minutes=expired_minutes_ago)).isoformat()})
            state["queue"][CLASS].append({"coordinator": "a", "holder": "next run", "id": "a-next", "priority": 0,
                                          "since": t.isoformat(), "minutes": 10, "gib": 1, "cpus": 1, "commands": "make",
                                          "worktree": self.tree, "project": self.m.project_key(self.tree)[0]})
            self.m.save(state, self.m.load_machine())
        finally:
            self.m.unlock()

    def held(self):
        return [h["id"] for h in self.m.load()[CLASS]]

    def inbox(self):
        if not os.path.exists(self.m.INBOX):
            return []
        return [json.loads(x) for x in open(self.m.INBOX) if x.strip()]

    def test_idle_lease_is_reclaimed_after_the_grace_period(self):
        self.hold("a-old", 11)
        self.assertEqual(self.c.reclaim_expired(CLASS, {}), ["a-old"])
        self.assertNotIn("a-old", self.held())
        lines = [r for r in self.inbox() if r["message"].startswith("AUTO-RECLAIMED")]
        self.assertEqual(sorted(r["to"] for r in lines), ["a", "builder"])
        self.assertIn("result=fail", open(self.m.LOG).read())
        self.c.auto_step(CLASS, None)
        self.assertEqual(self.held(), ["a-next"])  # the queue moves on

    def test_no_reclaim_inside_the_grace_period(self):
        self.hold("a-old", 5)
        self.assertEqual(self.c.reclaim_expired(CLASS, {}), [])
        self.assertIn("a-old", self.held())

    def test_no_reclaim_while_a_process_runs_in_the_worktree(self):
        self.procs.append(subprocess.Popen(["sleep", "60"], cwd=self.tree, start_new_session=True))
        self.hold("a-old", 30)
        self.assertEqual(self.c.reclaim_expired(CLASS, {}), [])
        self.assertIn("a-old", self.held())
        self.assertEqual([r for r in self.inbox() if r["message"].startswith("AUTO-RECLAIMED")], [])

    def test_helper_waiting_in_the_worktree_does_not_block_reclaim(self):
        helpers = os.path.join(self.tmp.name, "helpers")  # a skill copy: puppet.py beside moplib.py
        os.makedirs(helpers)
        open(os.path.join(helpers, "moplib.py"), "w").close()
        with open(os.path.join(helpers, "puppet.py"), "w") as f:
            f.write("import time\ntime.sleep(60)\n")
        self.procs.append(subprocess.Popen([sys.executable, "-I", os.path.join(helpers, "puppet.py"), "await-grant",
                                            "--id", "a-next"], cwd=self.tree, start_new_session=True))
        self.hold("a-old", 30)
        self.assertEqual(self.c.reclaim_expired(CLASS, {}), ["a-old"])  # the member's next await-grant is not a run

    def test_reclaim_minutes_zero_turns_it_off(self):
        self.config(reclaim=0)
        self.hold("a-old", 120)
        self.assertEqual(self.c.reclaim_expired(CLASS, {}), [])
        self.assertIn("a-old", self.held())

    def test_pool_class_defaults_to_off(self):
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {
            "VM": {"description": "vm", "defaultGiB": 0, "maxMinutes": 0, "settle": {}, "pool": {"create": "true"}}}})
        self.assertEqual(self.m.reclaim_minutes("VM"), 0)
        self.config(reclaim=None)
        self.assertEqual(self.m.reclaim_minutes(CLASS), self.m.RECLAIM_MINUTES)


if __name__ == "__main__":
    unittest.main()
