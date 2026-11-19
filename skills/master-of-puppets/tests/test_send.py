"""coordinator.py send: one command for every message from a coordinator.
Run: python3 -I skills/master-of-puppets/tests/test_send.py
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


class Send(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # the helpers read JSON with open() and no close
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = os.path.join(self.tmp.name, "state")
        os.makedirs(os.environ["MACHINE_LEASE_DIR"])
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.c = importlib.import_module("coordinator")
        self.m.RUN.env = {"MOP_ACTOR": "a"}
        self.sent = []
        self.c.deliver = lambda name, tool, sid, text: self.sent.append((name, text)) or f"{name}: delivered (test)"
        roster = self.m.load_roster()
        now = self.m.now().isoformat()
        roster["coordinators"]["a"] = {"heartbeat": now, "focus": "a", "prs": [], "tool": "claude", "sessionId": "sa"}
        roster["coordinators"]["b"] = {"heartbeat": now, "focus": "b", "prs": [], "tool": "codex", "sessionId": "tb"}
        roster["members"]["a"] = [{"name": "gw", "tool": "claude", "sessionId": "s1", "session": "claude://x/local_1",
                                   "status": "active"}]
        roster["members"]["b"] = [{"name": "bx", "tool": "codex", "sessionId": "t2", "status": "active"}]
        self.m.save_roster(roster)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def send(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.c.main(["send", *argv])
        return code, buf.getvalue()

    def inbox(self):
        return [json.loads(x) for x in open(self.m.INBOX) if x.strip()] if os.path.exists(self.m.INBOX) else []

    def test_to_a_coordinator_is_recorded_and_delivered(self):
        code, out = self.send("--to", "b", "--text", "PR #5 waits for #4.")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.inbox()[-1]["to"], "b")
        self.assertEqual(self.sent, [("b", "[a via coordinator.py send] PR #5 waits for #4.")])

    def test_to_all_reaches_every_live_peer(self):
        self.send("--to", "all", "--text", "WORK REQUEST")
        self.assertEqual([n for n, _ in self.sent], ["b"])
        self.assertNotIn("to", self.inbox()[-1])

    def test_to_a_member_prints_its_app_route(self):
        code, out = self.send("--to", "gw", "--text", "ACTIVE — #5.")
        self.assertEqual(code, 0, out)
        self.assertIn("SendMessage to claude://x/local_1", out)
        self.assertEqual(self.sent, [])  # no socket message without --direct
        self.assertEqual(self.inbox()[-1]["to"], "gw")
        self.send("--to", "gw", "--text", "ACTIVE — #5.", "--direct")
        self.assertEqual([n for n, _ in self.sent], ["gw"])

    def test_another_coordinators_member_is_refused(self):
        code, out = self.send("--to", "bx", "--text", "hi")
        self.assertEqual(code, 3)
        self.assertIn("member of b: message b instead", out)
        self.assertEqual(self.inbox(), [])

    def test_long_text_needs_a_file(self):
        code, out = self.send("--to", "b", "--text", "x" * 1300)
        self.assertEqual(code, 2)
        self.assertIn("--file", out)
        path = os.path.join(self.tmp.name, "details.md")
        open(path, "w").write("x" * 5000)
        code, out = self.send("--to", "b", "--text", "Release report.", "--file", path)
        self.assertEqual(code, 0, out)
        self.assertIn(f"Details: {path}", self.sent[-1][1])


if __name__ == "__main__":
    unittest.main()
