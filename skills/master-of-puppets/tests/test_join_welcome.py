"""JOIN errors name the missing field, join saves the WELCOME and prints how to deliver it, watch and pr agree
on auto-merge in the merge queue, and a scout command finds its coordinator in the roster.
Run: python3 -I skills/master-of-puppets/tests/test_join_welcome.py
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
JOIN = "JOIN — w — claude s1 — {wt} — fix the thing — PRs none — Starting — none — parent none — ephemeral"


class JoinWelcome(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # the helpers read JSON with open() and no close
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "state")
        os.environ["MACHINE_LEASE_DIR"] = self.dir
        os.makedirs(self.dir)
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator", "puppet"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.c = importlib.import_module("coordinator")
        self.p = importlib.import_module("puppet")
        self.m.RUN.env = {"MOP_ACTOR": "a"}
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": [], "tool": "claude"}
        roster["members"]["a"] = [{"name": "sc", "role": "scout", "status": "active", "tickMin": 15}]
        self.m.save_roster(roster)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def test_a_short_join_names_the_missing_field(self):
        cases = {
            "JOIN — w — claude s — /w — t — PRs none — phase — parent none — ephemeral": "between PRs and parent",
            "JOIN — w — claude s — /w — t — PRs none — phase — none — ephemeral": "parent <name|none>",
            "JOIN — w — claude s — /w — t — phase — none — parent none — ephemeral": "the PRs field",
            "JOIN — w — claude s — /w — t — PRs none — phase — none — parent none": "ephemeral or long-running",
        }
        for line, want in cases.items():
            with self.assertRaises(ValueError) as e:
                self.c.parse_join(line)
            self.assertIn("9 fields", str(e.exception))
            self.assertIn(want, str(e.exception))

    def test_join_saves_the_welcome_and_prints_its_delivery(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.c.main(["join", "--text", JOIN.format(wt=self.tmp.name)])
        self.assertEqual(code, 0)
        path = os.path.join(self.dir, "welcome", "a-w.txt")
        self.assertTrue(open(path).read().startswith("WELCOME w — a coordinates test."))
        text = out.getvalue()
        self.assertIn("SendMessage to s1", text)
        self.assertIn(f"WELCOME w: a recorded your JOIN. Read the full WELCOME at {path}", text)
        self.assertIn(path, open(self.m.INBOX).read())

    def test_welcome_includes_machine_and_project_workflow_files(self):
        mw = self.m.workflow_path()[0]
        pw = self.m.workflow_path(self.tmp.name)[0]
        os.makedirs(os.path.dirname(mw), exist_ok=True)
        open(mw, "w").write("# Machine workflows\n")
        open(pw, "w").write("# Project workflows\n")
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.c.main(["join", "--text", JOIN.format(wt=self.tmp.name)])
        self.assertEqual(code, 0)
        welcome = open(os.path.join(self.dir, "welcome", "a-w.txt")).read()
        self.assertIn(f"Machine workflow instructions: {mw}", welcome)
        self.assertIn(f"Project workflow instructions: {pw}", welcome)

    def test_watch_and_pr_agree_on_a_queued_pr(self):
        # GitHub clears autoMergeRequest when the PR enters the merge queue
        d = {"state": "OPEN", "baseRefName": "main", "isDraft": False, "mergeStateStatus": "CLEAN",
             "autoMergeRequest": None, "isInMergeQueue": True, "mergeQueueEntry": {"position": 9, "state": "QUEUED"}}
        self.assertEqual(self.m.automerge_state(d), "queued(pos=9,QUEUED)")
        self.assertIn("automerge=queued(QUEUED)", self.m.pr_line(d))  # no position: a queue move is no event
        self.assertIn("isInMergeQueue", self.m.PR_GQL)
        self.assertEqual(self.m.automerge_state({**d, "isInMergeQueue": False}), "off")
        self.assertEqual(self.m.automerge_state({**d, "state": "MERGED"}), "merged")
        sys.modules.pop("server", None)
        flag = importlib.import_module("server").automerge_flag
        # a record cached before the change holds a bool, and a merged PR is not fetched again
        self.assertEqual([flag(v) for v in (True, False, None, "off", "merged", "on", "queued(pos=9,QUEUED)")],
                         ["auto-merge on", "", "", "", "", "auto-merge on", "auto-merge queued(pos=9,QUEUED)"])

    def test_a_scout_command_finds_its_coordinator(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.p.main(["scout", "tick", "--name", "sc", "--state", "cursor 1"]), 0)
            self.assertEqual(self.p.main(["scout", "show", "--name", "sc"]), 0)
            self.assertEqual(self.p.main(["scout", "show", "--name", "nobody"]), 3)
        self.assertEqual(self.m.scout_state("sc")["state"]["text"], "cursor 1")
        roster = self.m.load_roster()
        roster["coordinators"]["b"] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": []}
        roster["members"]["b"] = [{"name": "sc", "role": "scout", "status": "active", "tickMin": 15}]
        self.m.save_roster(roster)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.p.main(["scout", "show", "--name", "sc"]), 3)
        self.assertIn("give --coordinator", out.getvalue())


if __name__ == "__main__":
    unittest.main()
