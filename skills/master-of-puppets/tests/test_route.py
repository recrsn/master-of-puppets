"""A coordinator's T3 Code thread is recorded at its heartbeat, puppet.py route prints the routes best first,
and puppet.py tell gives a member an inbox fallback in its own name only.
Run: python3 -I skills/master-of-puppets/tests/test_route.py
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


class Route(unittest.TestCase):
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
        self.p = importlib.import_module("puppet")
        self.sent = []
        self.p.deliver = lambda name, tool, sid, text: self.sent.append((name, text)) or f"{name}: delivered (test)"
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "a", "prs": [],
                                       "tool": "claude", "sessionId": "sa"}
        roster["members"]["a"] = [{"name": "w", "tool": "claude", "sessionId": "s1", "status": "active"},
                                  {"name": "gone", "tool": "claude", "sessionId": "s2", "status": "done"}]
        self.m.save_roster(roster)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def run_cli(self, mod, env, *argv):
        self.m.RUN.env = env
        out = io.StringIO()
        with redirect_stdout(out):
            code = mod.main(list(argv))
        return code, out.getvalue()

    def coord(self):
        return self.m.load_roster()["coordinators"]["a"]

    def test_the_heartbeat_records_the_thread_and_only_the_coordinator_changes_it(self):
        own = {"CLAUDE_CODE_SESSION_ID": "sa", "T3CODE_THREAD_ID": "th-1"}
        self.assertEqual(self.run_cli(self.c, own, "heartbeat", "--name", "a")[0], 0)
        self.assertEqual(self.coord()["t3Thread"], "th-1")
        self.run_cli(self.c, {"MOP_ACTOR": "a"}, "heartbeat", "--name", "a")  # the dashboard knows no thread
        self.assertEqual(self.coord()["t3Thread"], "th-1")
        self.run_cli(self.c, {"CLAUDE_CODE_SESSION_ID": "sa"}, "heartbeat", "--name", "a")  # moved off T3 Code
        self.assertNotIn("t3Thread", self.coord())

    def test_a_connected_watch_also_records_the_thread(self):
        self.m.RUN.env = {"CLAUDE_CODE_SESSION_ID": "sa", "T3CODE_THREAD_ID": "th-2"}
        self.c.renew_heartbeat("a")
        self.assertEqual(self.coord()["t3Thread"], "th-2")

    def test_route_lists_the_thread_first_and_finds_the_callers_coordinator(self):
        self.run_cli(self.c, {"CLAUDE_CODE_SESSION_ID": "sa", "T3CODE_THREAD_ID": "th-1"}, "heartbeat", "--name", "a")
        code, out = self.run_cli(self.p, {"CLAUDE_CODE_SESSION_ID": "s1"}, "route")
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertIn("coordinator a (claude in T3 Code, live", lines[0])
        self.assertIn("t3_thread_send with threadId th-1", lines[1])
        self.assertIn("SendMessage to sa", lines[2])
        self.assertIn("puppet.py tell", lines[3])
        code, out = self.run_cli(self.p, {"CLAUDE_CODE_SESSION_ID": "s2"}, "route")  # a done member
        self.assertEqual(code, 0)  # the one live coordinator is still the route, with a whoami hint
        self.assertIn("run puppet.py whoami", out)
        roster = self.m.load_roster()
        roster["coordinators"]["b"] = dict(roster["coordinators"]["a"], sessionId="sb")
        self.m.save_roster(roster)
        self.assertEqual(self.run_cli(self.p, {"CLAUDE_CODE_SESSION_ID": "s2"}, "route")[0], 3)  # two: it must choose

    def test_a_members_command_records_its_thread_for_the_coordinators_route(self):
        self.run_cli(self.p, {"CLAUDE_CODE_SESSION_ID": "s1", "T3CODE_THREAD_ID": "mt-1"}, "route")
        m = self.m.load_roster()["members"]["a"][0]
        self.assertEqual(m["t3Thread"], "mt-1")
        self.assertIn("t3_thread_send with threadId mt-1", self.c.native_route(m))
        self.run_cli(self.p, {"CLAUDE_CODE_SESSION_ID": "stranger", "T3CODE_THREAD_ID": "x"}, "route", "--coordinator", "a")
        self.assertNotIn("t3Thread", self.m.load_roster()["members"]["a"][1])  # nobody else's entry changes

    def test_tell_writes_the_inbox_in_the_callers_own_name(self):
        code, out = self.run_cli(self.p, {"CLAUDE_CODE_SESSION_ID": "s1"}, "tell", "--text", "UPDATE — w — blocked")
        self.assertEqual(code, 0, out)
        rec = [json.loads(x) for x in open(self.m.INBOX)][-1]
        self.assertEqual((rec["from"], rec["to"], rec["message"]), ("w", "a", "UPDATE — w — blocked"))
        self.assertEqual(self.sent, [("a", "[w via puppet.py tell] UPDATE — w — blocked")])
        code, out = self.run_cli(self.p, {"CLAUDE_CODE_SESSION_ID": "stranger"}, "tell", "--text", "hi")
        self.assertEqual(code, 3)
        self.assertIn("send JOIN", out)
        self.assertEqual(self.run_cli(self.p, {"CLAUDE_CODE_SESSION_ID": "s1"}, "tell", "--text", "x" * 1300)[0], 2)


if __name__ == "__main__":
    unittest.main()
