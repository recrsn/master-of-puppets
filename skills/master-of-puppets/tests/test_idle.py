"""Long-running members: the JOIN's last field (ephemeral|long-running), IDLE between tasks, and the wake.
Run: python3 -I skills/master-of-puppets/tests/test_idle.py
Each test runs in its own empty MACHINE_LEASE_DIR; nothing touches the live state, sends a message or calls GitHub."""
import datetime as dt
import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
CLASS = "BUILD"


class Idle(unittest.TestCase):
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
        self.m.RUN.env = {"MOP_ACTOR": "a"}
        self.sent = []
        self.c.deliver = lambda name, tool, sid, text: self.sent.append((name, text)) or "not delivered (test)"
        self.prs = {}
        self.c.pr_digests = lambda refs: {r: {"state": self.prs.get(r[1], "MERGED"), "mergeCommit": "abc"} for r in refs}
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {CLASS: dict(self.m.DEFAULT_REGISTRY[CLASS])}})
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": []}
        self.m.save_roster(roster)
        self.tree = os.path.join(self.tmp.name, "wt")
        os.makedirs(self.tree)
        subprocess.run(["git", "init", "-q", self.tree], check=True)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def run_cmd(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.c.main(argv)
        return code, buf.getvalue()

    def join(self, life="long-running", prs="PRs none"):
        line = f"JOIN — gw — claude abc-123 — {self.tree} — answer questions — {prs} — Ready — none — parent none — {life}"
        return self.run_cmd(["join", "--text", line, "--repo", "o/r"])

    def member(self):
        return next(x for x in self.m.load_roster()["members"]["a"] if x["name"] == "gw")

    def test_join_reads_the_lifetime_field(self):
        j = self.c.parse_join(f"JOIN — gw — claude x — {self.tree} — a — task — PRs #1 (base main) — Coding — make — parent none — long running")
        self.assertEqual((j["life"], j["task"], j["prs"], j["phase"], j["commands"]), ("long-running", "a — task", [1], "Coding", "make"))
        with self.assertRaises(ValueError):  # hard cutover: the old JOIN with no lifetime field is refused
            self.c.parse_join(f"JOIN — gw — claude x — {self.tree} — task — PRs none — Coding — make — parent none")
        code, out = self.join()
        self.assertEqual(code, 0)
        self.assertIn("You are long-running", out)
        self.assertEqual(self.member()["life"], "long-running")

    def test_ephemeral_member_may_not_idle(self):
        self.join(life="ephemeral")
        code, out = self.run_cmd(["idle", "--name", "gw", "--wake", "a new question"])
        self.assertEqual(code, 1)
        self.assertIn("ephemeral", out)
        self.assertEqual(self.member()["status"], "active")

    def test_idle_refused_while_work_is_left(self):
        self.join(prs="PRs #7")
        self.prs[7] = "OPEN"
        with open(os.path.join(self.tree, "x"), "w") as f:
            f.write("x")
        self.m.lock()
        try:
            state = self.m.load()
            state["queue"][CLASS].append({"coordinator": "a", "holder": "gw build", "id": "a-q-gw-1", "priority": 0,
                                          "since": self.m.now().isoformat(), "minutes": 5, "gib": 1, "cpus": 1,
                                          "commands": "make", "worktree": self.tree, "project": "p"})
            self.m.save(state, self.m.load_machine())
        finally:
            self.m.unlock()
        code, out = self.run_cmd(["idle", "--name", "gw", "--wake", "a new question"])
        self.assertEqual(code, 1)
        for part in ("#7 is OPEN", "uncommitted changes", "a-q-gw-1"):
            self.assertIn(part, out)
        self.assertEqual(self.member()["status"], "active")
        code, out = self.run_cmd(["idle", "--name", "gw", "--reject", "--reason", "PR #7 is open"])
        self.assertEqual(code, 0)
        self.assertIn("IDLE NOT ACCEPTED", self.sent[-1][1])

    def test_idle_member_is_quiet_and_wakes_on_new_work(self):
        self.join(prs="PRs #7")  # #7 is MERGED
        code, out = self.run_cmd(["idle", "--name", "gw", "--wake", "a new question from the user"])
        self.assertEqual(code, 0, out)
        self.assertIn("IDLE ACCEPTED", self.sent[-1][1])
        m = self.member()
        self.assertEqual((m["status"], m["wake"]), ("idle", "a new question from the user"))

        roster = self.m.load_roster()  # silent for hours: not stale, and no Needs-you card
        for x in roster["members"]["a"]:
            x["updatedAt"] = (self.m.now() - dt.timedelta(hours=5)).isoformat()
        self.m.save_roster(roster)
        code, out = self.run_cmd(["member", "stale", "--minutes", "30"])
        self.assertIn("no member silent", out)
        page = str(importlib.import_module("server").render_page({}))
        self.assertNotIn("No update for", page)

        code, out = self.run_cmd(["heartbeat", "--status", "idle"])  # an idle member does not keep C awake
        self.assertEqual(code, 0, out)
        self.assertEqual(self.m.load_roster()["coordinators"]["a"]["status"], "idle")

        code, out = self.run_cmd(["member", "update", "--name", "gw", "--phase", "Answering"])
        self.assertEqual(code, 0, out)
        m = self.member()
        self.assertEqual(m["status"], "active")
        self.assertNotIn("idleSince", m)
        self.assertEqual(self.m.load_roster()["coordinators"]["a"]["status"], "active")  # the wake also wakes C


if __name__ == "__main__":
    unittest.main()
