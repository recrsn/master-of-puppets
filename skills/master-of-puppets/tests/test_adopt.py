"""Whole-coordinator handoffs: member accept, resign --to with adopt, and adopt after a plain resign.
Run: python3 -I skills/master-of-puppets/tests/test_adopt.py
Each test runs in its own empty MACHINE_LEASE_DIR; nothing touches the live state or sends a message."""
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
CLASS = "BUILD"


class Adopt(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # the helpers read JSON with open() and no close
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "state")
        os.environ["MACHINE_LEASE_DIR"] = self.dir
        os.makedirs(self.dir)
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.c = importlib.import_module("coordinator")
        self.c.deliver = lambda name, tool, sid, text: f"{name}: delivered (test)"
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {CLASS: dict(self.m.DEFAULT_REGISTRY[CLASS])}})
        roster = self.m.load_roster()
        for coord in ("a", "b", "x"):
            roster["coordinators"][coord] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": [],
                                             "tool": "claude", "sessionId": f"s-{coord}"}
        roster["coordinators"]["a"]["prs"] = [7]
        roster["members"]["a"] = [
            {"name": "w1", "tool": "claude", "sessionId": "m1", "status": "active", "prs": [11], "task": "one"},
            {"name": "w2", "tool": "codex", "sessionId": "m2", "status": "paused", "prs": [], "task": "two"},
            {"name": "old", "tool": "claude", "sessionId": "m3", "status": "done", "prs": [], "task": "done one"}]
        roster["streams"] = {"s-open": {"coordinator": "a", "label": "Open", "status": "open"},
                             "s-closed": {"coordinator": "a", "label": "Closed", "status": "closed"},
                             "s-other": {"coordinator": "x", "label": "Other", "status": "open"}}
        self.m.save_roster(roster)
        self.m.lock()
        try:
            state = self.m.load()
            state["queue"][CLASS].append({"coordinator": "a", "holder": "w1 build", "id": "a-q-w1-1", "priority": 0,
                                          "since": self.m.now().isoformat(), "minutes": 5, "gib": 1, "cpus": 0, "commands": "make"})
            state["queue"][CLASS].append({"coordinator": "a", "holder": "a own", "id": "a-own-1", "priority": 0,
                                          "since": self.m.now().isoformat(), "minutes": 5, "gib": 1, "cpus": 0, "commands": "make"})
            self.m.save(state, self.m.load_machine())
        finally:
            self.m.unlock()
        self.m.write_json(self.c.state_path("a"), {"tasks": [{"id": "w1", "name": "one"}],
                                                   "decisions": [{"id": "d1", "text": "merge?", "task": "w1"},
                                                                 {"id": "d2", "text": "release?"}]})
        with open(os.path.join(self.dir, "prs-a.txt"), "w") as f:
            f.write("owner/repo#7 watch\nowner/repo#9\n")

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def run_as(self, actor, *argv):
        self.m.RUN.env = {"MOP_ACTOR": actor}
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.c.main(list(argv))
        return code, out.getvalue()

    def coords_of_leases(self):
        state = self.m.load()
        return {q["id"]: q["coordinator"] for q in state["queue"][CLASS] + state[CLASS]}

    def test_member_accept_moves_one_member_and_refuses_a_taken_name(self):
        self.assertEqual(self.run_as("a", "member", "transfer", "--name", "w1", "--to", "b")[0], 0)
        roster = self.m.load_roster()
        roster["members"]["b"] = [{"name": "w1", "status": "active"}]
        self.m.save_roster(roster)
        code, out = self.run_as("b", "member", "accept", "--name", "w1", "--from", "a")
        self.assertEqual(code, 3)
        self.assertIn("name_taken", out)
        roster["members"]["b"] = []
        self.m.save_roster(roster)
        code, out = self.run_as("b", "member", "accept", "--name", "w1", "--from", "a")
        self.assertEqual(code, 0, out)
        roster = self.m.load_roster()
        self.assertEqual([m["name"] for m in roster["members"]["b"]], ["w1"])
        self.assertEqual(roster["coordinators"]["b"]["prs"], [11])
        self.assertEqual(self.coords_of_leases(), {"a-q-w1-1": "b", "a-own-1": "a"})
        self.assertEqual([d["id"] for d in self.m.read_json(self.c.state_path("b"))["decisions"]], ["d1"])

    def test_resign_to_then_adopt_moves_the_whole_stack(self):
        code, out = self.run_as("a", "resign", "--to", "b", "--note", "/n/HANDOFF.md")
        self.assertEqual(code, 0, out)
        roster = self.m.load_roster()
        self.assertNotIn("a", roster["coordinators"])
        self.assertEqual({n: s["coordinator"] for n, s in roster["streams"].items()},
                         {"s-open": "b", "s-closed": "b", "s-other": "x"})
        self.assertIn("adopt --from a", open(self.m.INBOX).read())
        # another coordinator cannot take what was handed to b
        self.assertEqual(self.run_as("x", "adopt", "--from", "a")[0], 3)
        code, out = self.run_as("b", "adopt", "--from", "a")
        self.assertEqual(code, 0, out)
        roster = self.m.load_roster()
        self.assertEqual(sorted(m["name"] for m in roster["members"]["b"]), ["w1", "w2"])
        self.assertEqual(sorted(roster["coordinators"]["b"]["prs"]), [7, 11])
        self.assertNotIn("a", roster.get("handoffs", {}))
        self.assertEqual(set(self.coords_of_leases().values()), {"b"})
        self.assertEqual(sorted(d["id"] for d in self.m.read_json(self.c.state_path("b"))["decisions"]), ["d1", "d2"])
        self.assertIn("owner/repo#9", open(os.path.join(self.dir, "prs-b.txt")).read())
        self.assertFalse(os.path.exists(os.path.join(self.dir, "prs-a.txt")))
        self.assertIn("HANDOFF COMPLETE — w1 — JOIN b", out)
        self.assertIn("send_message_to_thread with threadId m2", out)

    def test_adopt_after_a_plain_resign(self):
        code, out = self.run_as("a", "resign")
        self.assertEqual(code, 0)
        left = json.loads(out)["left_without_owner"]
        self.assertEqual(left, {"members": ["w1", "w2"], "streams": ["s-closed", "s-open"], "prs": [7]})
        code, out = self.run_as("b", "adopt", "--from", "a")
        self.assertEqual(code, 0, out)
        roster = self.m.load_roster()
        self.assertEqual(sorted(m["name"] for m in roster["members"]["b"]), ["w1", "w2"])
        self.assertEqual(roster["streams"]["s-open"]["coordinator"], "b")
        self.assertEqual(set(self.coords_of_leases().values()), {"b"})
        self.assertEqual(sorted(roster["coordinators"]["b"]["prs"]), [7, 11])
        self.assertNotIn("a", roster.get("handoffs", {}))
        self.assertIn("owner/repo#7", open(os.path.join(self.dir, "prs-b.txt")).read())

    def test_adopt_from_a_registered_coordinator_that_offered_nothing(self):
        code, out = self.run_as("b", "adopt", "--from", "a")
        self.assertEqual(code, 3)
        self.assertIn("resign --to b", out)
        self.assertEqual(len(self.m.load_roster()["members"]["a"]), 3)


if __name__ == "__main__":
    unittest.main()
