"""Head-of-line stalls in the auto grant: a head entry that waits for its own coordinator is passed over
after stallMinutes (or at once when its coordinator is not live), keeps its place, and goes first again
once its coordinator acts. Run: python3 -I skills/master-of-puppets/tests/test_stalls.py
Each test runs in its own empty MACHINE_LEASE_DIR; nothing touches the live state."""
import datetime as dt
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
import warnings

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
CLASS = "BUILD"


class Stalls(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # the helpers read JSON with open() and no close
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = os.path.join(self.tmp.name, "state")
        os.makedirs(os.environ["MACHINE_LEASE_DIR"])
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator", "server"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.c = importlib.import_module("coordinator")
        self.m.RUN.env = {"MOP_ACTOR": "test"}
        self.c.host_check = lambda: (True, "CALM")
        self.c.subprocess = types.SimpleNamespace(Popen=lambda *a, **k: types.SimpleNamespace(pid=0), DEVNULL=None,
                                                  STDOUT=None, run=self.c.subprocess.run)
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {
            CLASS: {**self.m.DEFAULT_REGISTRY[CLASS], "autoAcquire": True, "stallMinutes": 20}}})
        roster = self.m.load_roster()
        for coord in ("a", "b"):
            roster["coordinators"][coord] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": []}
        self.m.save_roster(roster)
        self.big = self.worktree("big")  # observed peak 8 GiB: a 1 GiB request is undersized
        proj = self.m.load_project(self.m.project_key(self.big)[0])
        proj["classes"][CLASS]["samples"] = [8, 8, 8]
        self.m.save_project(proj)
        self.small = self.worktree("small")  # no samples: any size passes

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def worktree(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path)
        return path

    def queue(self, coord, entry_id, worktree, gib):
        self.m.lock()
        try:
            state = self.m.load()
            state["queue"][CLASS].append({"coordinator": coord, "holder": f"{entry_id} member", "id": entry_id, "priority": 0,
                                          "since": self.m.now().isoformat(), "minutes": 10, "gib": gib, "cpus": 1,
                                          "commands": "make", "worktree": worktree,
                                          "project": self.m.project_key(worktree)[0]})
            self.m.save(state, self.m.load_machine())
        finally:
            self.m.unlock()

    def edit(self, fn):
        self.m.lock()
        try:
            state = self.m.load()
            fn(state)
            self.m.save(state, self.m.load_machine())
        finally:
            self.m.unlock()

    def backdate_stall(self, entry_id, minutes):
        def fn(state):
            q = next(q for q in state["queue"][CLASS] if q["id"] == entry_id)
            q["stall"]["since"] = (self.m.now() - dt.timedelta(minutes=minutes)).isoformat()
        self.edit(fn)

    def step(self):
        self.c.auto_step(CLASS, None)

    def held(self):
        return [h["id"] for h in self.m.load()[CLASS]]

    def queued(self):
        return [q["id"] for q in self.m.load()["queue"][CLASS]]

    def entry(self, entry_id):
        return next(q for q in self.m.load()["queue"][CLASS] if q["id"] == entry_id)

    def inbox(self):
        if not os.path.exists(self.m.INBOX):
            return []
        return [json.loads(x) for x in open(self.m.INBOX) if x.strip()]

    def test_undersized_head_is_passed_over_after_stall_minutes(self):
        self.queue("a", "a-1", self.big, 1)
        self.queue("b", "b-1", self.small, 1)
        self.step()
        self.assertEqual(self.held(), [])  # inside stallMinutes: the head blocks the queue
        self.assertFalse(self.entry("a-1")["stall"]["stalled"])
        self.backdate_stall("a-1", 21)
        self.step()
        self.assertEqual(self.held(), ["b-1"])
        self.assertEqual(self.queued(), ["a-1"])  # keeps its place
        self.assertTrue(self.m.stalled(self.entry("a-1")))
        stalls = [r for r in self.inbox() if r["message"].startswith("AUTO-STALLED")]
        self.assertEqual([r["to"] for r in stalls], ["a"])
        self.step()
        self.assertEqual(len([r for r in self.inbox() if r["message"].startswith("AUTO-STALLED")]), 1)  # sent once

    def test_stalled_head_goes_first_once_its_coordinator_acts(self):
        self.queue("a", "a-1", self.big, 1)
        self.queue("b", "b-1", self.small, 1)
        self.queue("b", "b-2", self.small, 1)
        self.step()
        self.backdate_stall("a-1", 21)
        self.step()
        self.assertEqual(self.held(), ["b-1"])

        def resize(state):
            next(q for q in state["queue"][CLASS] if q["id"] == "a-1")["gib"] = 8
        self.edit(resize)
        self.step()
        self.assertEqual(self.held(), ["b-1", "a-1"])  # no starvation: a-1 goes before b-2
        self.assertEqual(self.queued(), ["b-2"])

    def test_stalled_head_can_still_be_acquired_by_its_coordinator(self):
        self.queue("a", "a-1", self.big, 1)
        self.queue("b", "b-1", self.small, 1)
        self.step()
        self.backdate_stall("a-1", 21)
        self.step()
        self.assertIsNone(self.m.blocked_by(self.m.load()["queue"][CLASS], "a-1"))
        self.m.RUN.env = {"MOP_ACTOR": "a"}
        code = self.c.main(["acquire", CLASS, "--coordinator", "a", "--holder", "a-1 member", "--id", "a-1",
                            "--worktree", self.big, "--minutes", "10", "--accept-size"])
        self.assertEqual(code, 0)
        self.assertIn("a-1", self.held())

    def test_dashboard_shows_the_stall_under_needs_you(self):
        self.queue("a", "a-1", self.big, 1)
        self.queue("b", "b-1", self.small, 1)
        self.step()
        self.backdate_stall("a-1", 21)
        self.step()
        server = importlib.import_module("server")
        page = str(server.render_page({}))
        needs = page[page.index("Needs you"):]
        self.assertIn("Stalled BUILD request", needs)
        self.assertIn("passed over", page)

    def test_head_of_a_stale_coordinator_is_passed_over_at_once(self):
        def stale(roster):
            roster["coordinators"]["a"]["heartbeat"] = (self.m.now() - dt.timedelta(hours=2)).isoformat()
        roster = self.m.load_roster()
        stale(roster)
        self.m.save_roster(roster)
        self.queue("a", "a-1", self.big, 1)
        self.queue("b", "b-1", self.small, 1)
        self.step()
        self.step()
        self.assertEqual(self.held(), ["b-1"])
        self.assertTrue(self.m.stalled(self.entry("a-1")))

    def test_head_refused_on_budget_never_stalls(self):
        self.queue("a", "a-1", self.small, 100000)
        self.queue("b", "b-1", self.small, 1)
        for _ in range(2):
            self.step()
        self.assertNotIn("stall", self.entry("a-1"))
        self.assertEqual(self.held(), [])  # a large head is not starved by small entries behind it

    def test_stall_minutes_zero_turns_stalls_off(self):
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {
            CLASS: {**self.m.DEFAULT_REGISTRY[CLASS], "autoAcquire": True, "stallMinutes": 0}}})
        roster = self.m.load_roster()
        roster["coordinators"]["a"]["heartbeat"] = (self.m.now() - dt.timedelta(hours=2)).isoformat()
        self.m.save_roster(roster)
        self.queue("a", "a-1", self.big, 1)
        self.queue("b", "b-1", self.small, 1)
        self.step()
        self.step()
        self.assertEqual(self.held(), [])
        self.assertNotIn("stall", self.entry("a-1"))


if __name__ == "__main__":
    unittest.main()
