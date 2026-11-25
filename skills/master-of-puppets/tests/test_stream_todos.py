"""Each stream keeps a todo list; the round's streams section asks for a check-in when the list stops moving,
once, and says NO-ANSWER when the check-in brings no progress.
Run: python3 -I skills/master-of-puppets/tests/test_stream_todos.py
Each test runs in its own empty MACHINE_LEASE_DIR; nothing touches the live state or sends a message."""
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


class StreamTodos(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = os.path.join(self.tmp.name, "state")
        os.makedirs(os.environ["MACHINE_LEASE_DIR"])
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.c = importlib.import_module("coordinator")
        roster = self.m.load_roster()
        t = self.m.now().isoformat()
        for coord in ("a", "b"):
            roster["coordinators"][coord] = {"heartbeat": t, "focus": "x", "prs": [], "tool": "claude", "sessionId": f"s-{coord}"}
        roster["members"]["a"] = [{"name": "w1", "tool": "claude", "sessionId": "m1", "status": "active", "stream": "api",
                                   "updatedAt": t, "task": "one"},
                                  {"name": "w2", "tool": "claude", "sessionId": "m2", "status": "paused", "stream": "docs",
                                   "updatedAt": t, "task": "two"}]
        roster["streams"] = {"api": {"coordinator": "a", "label": "API", "status": "open", "createdAt": t},
                             "docs": {"coordinator": "a", "label": "Docs", "status": "open", "createdAt": t},
                             "old": {"coordinator": "a", "label": "Old", "status": "closed", "createdAt": t},
                             "theirs": {"coordinator": "b", "label": "B", "status": "open", "createdAt": t}}
        self.m.save_roster(roster)
        self.m.RUN.env = {"CLAUDE_CODE_SESSION_ID": "s-a"}

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def run_cli(self, *argv, env=None):
        if env:
            self.m.RUN.env = env
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = self.c.main(list(argv))
        return code, out.getvalue()

    def age(self, minutes, *fields):
        roster = self.m.load_roster()
        s = roster["streams"]["api"]
        for f in fields:
            if s.get(f):
                s[f] = (self.m.dt.datetime.fromisoformat(s[f]) - self.m.dt.timedelta(minutes=minutes)).isoformat()
        self.m.save_roster(roster)

    def todo(self, *args):
        code, output = self.run_cli("stream", "todo", *args, "--name", "api")
        self.assertEqual(code, 0, output)
        return output

    def test_structured_details_and_progress_on_an_existing_todo(self):
        roster = self.m.load_roster()
        roster["streams"]["api"]["todos"] = [
            {"id": 7, "text": "Restore a backup", "status": "doing", "owner": "w1",
             "updatedAt": self.m.now().isoformat()}
        ]
        self.m.save_roster(roster)
        target = ("--id", "7")
        item = json.loads(self.todo("show", *target))
        self.assertEqual(item["requirements"], [])
        self.assertEqual(item["subtasks"], [])
        self.assertEqual(item["verification"]["status"], "unverified")
        self.assertIn("7. [doing] Restore a backup (w1)", self.todo("list"))

        self.todo("req", "add", *target, "--text", "Keep timestamps")
        self.todo("req", "add", *target, "--text", "Keep comments")
        self.todo("req", "remove", *target, "--text", "Keep comments")
        self.todo("sub", "add", *target, "--text", "Read archive")
        self.todo("sub", "add", *target, "--text", "Compare timestamps")
        self.todo("sub", "set", *target, "--sub-id", "2", "--status", "done", "--note", "Timestamps match")

        item = json.loads(self.todo("show", *target))
        self.assertEqual(item["requirements"], ["Keep timestamps"])
        self.assertEqual([(s["id"], s["text"], s["status"]) for s in item["subtasks"]],
                         [(1, "Read archive", "todo"), (2, "Compare timestamps", "done")])
        self.assertEqual(item["subtasks"][1]["note"], "Timestamps match")
        self.assertEqual(item["status"], "doing")
        out = self.todo("list")
        self.assertIn("requirements: 1", out)
        self.assertIn("subtasks: 1/2", out)
        self.assertIn("verification: unverified", out)

    def test_verification_belongs_to_the_checked_scope(self):
        self.todo("add", "--text", "Restore a backup")
        target = ("--id", "1")
        for verdict, sha, note in [("failed", "a" * 40, "Comments lost"),
                                   ("passed", "b" * 40, "Comments restored")]:
            self.todo("verify", *target, "--status", verdict, "--pr", "42", "--sha", sha, "--note", note)
            receipt = json.loads(self.todo("show", *target))["verification"]
            self.assertEqual((receipt["status"], receipt["pr"], receipt["sha"], receipt["summary"]),
                             (verdict, 42, sha, note))
            self.assertIsNotNone(self.m.dt.datetime.fromisoformat(receipt["verifiedAt"]).tzinfo)
            self.assertIn("verification: " + verdict, self.todo("list"))

        self.todo("set", *target, "--status", "done")
        self.assertEqual(json.loads(self.todo("show", *target))["verification"], receipt)
        self.todo("req", "add", *target, "--text", "Keep timestamps")
        self.assertEqual(json.loads(self.todo("show", *target))["verification"], {
            "status": "unverified", "pr": None, "sha": None, "summary": None, "verifiedAt": None,
        })

    def test_add_set_and_list(self):
        self.assertEqual(self.run_cli("stream", "todo", "add", "--name", "api", "--text", "fix auth", "--owner", "w1")[0], 0)
        self.assertEqual(self.run_cli("stream", "todo", "add", "--name", "api", "--text", "add tests")[0], 0)
        self.assertEqual(self.run_cli("stream", "todo", "set", "--name", "api", "--id", "1", "--status", "doing")[0], 0)
        self.assertEqual(self.run_cli("stream", "todo", "set", "--name", "api", "--id", "2", "--status", "blocked")[0], 2)
        out = self.run_cli("stream", "todo", "list", "--name", "api")[1]
        self.assertIn("1. [doing] fix auth (w1)", out)
        self.assertIn("2. [open] add tests", out)
        self.assertEqual(self.run_cli("stream", "todo", "add", "--name", "api", "--text", "x", "--owner", "nobody")[0], 3)

    def test_only_the_owner_changes_the_list(self):
        code, out = self.run_cli("stream", "todo", "add", "--name", "theirs", "--text", "x")
        self.assertEqual(code, 3)
        self.assertIn("owned_by", out)

    def test_stale_list_gets_one_check_in_then_no_answer(self):
        out = self.run_cli("stream", "stale")[1]
        self.assertIn("NO-LIST api", out)
        self.assertNotIn("docs", out)  # every member paused
        self.assertNotIn("old", out)  # closed
        self.assertNotIn("theirs", out)  # another coordinator's
        roster = self.m.load_roster()
        roster["streams"]["idle"] = {"coordinator": "a", "label": "Idle", "status": "open", "createdAt": self.m.now().isoformat()}
        self.m.save_roster(roster)
        self.assertIn("NO-MEMBERS 1 open streams with no active member and no open todo: close each", self.run_cli("stream", "stale")[1])
        self.run_cli("stream", "close", "--name", "idle")
        self.run_cli("stream", "todo", "add", "--name", "api", "--text", "fix auth", "--owner", "w1")
        self.assertEqual(self.run_cli("stream", "stale")[1].strip(), "ok")  # fresh progress
        self.age(90, "todoAt")
        out = self.run_cli("stream", "stale")[1]
        self.assertIn("CHECK-IN api: no todo progress for 90 min", out)
        self.assertIn("STATUS request to w1 about: 1. fix auth", out)
        self.assertIn("members last update 0 min ago", out)
        self.assertEqual(self.run_cli("stream", "stale")[1].strip(), "ok")  # recorded: not repeated
        self.age(61, "checkinAt")
        self.assertIn("NO-ANSWER api", self.run_cli("stream", "stale")[1])
        self.run_cli("stream", "todo", "set", "--name", "api", "--id", "1", "--status", "done")
        self.assertIn("DONE-LIST api", self.run_cli("stream", "stale")[1])

    def test_a_handed_over_stream_keeps_its_todos(self):
        self.run_cli("stream", "todo", "add", "--name", "api", "--text", "fix auth")
        self.assertEqual(self.run_cli("stream", "update", "--name", "api", "--owner", "b")[0], 0)
        s = self.m.load_roster()["streams"]["api"]
        self.assertEqual((s["coordinator"], s["todos"][0]["text"]), ("b", "fix auth"))

    def test_the_round_has_a_streams_section(self):
        self.c.round_leases = lambda me: 0
        self.c.round_sessions = lambda me, active_only=False: 0
        self.c.round_prs = lambda me, open_only, hours: 0
        self.c.round_inbox = lambda me, since: 0
        out = self.run_cli("round")[1]
        self.assertIn("== streams without todo progress 60 min", out)
        self.assertIn("NO-LIST api", out)


if __name__ == "__main__":
    unittest.main()
