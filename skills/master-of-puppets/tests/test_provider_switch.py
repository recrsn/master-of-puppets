"""A T3 Code thread can switch provider in place (Claude to Antigravity ACP, for example): the session id
changes, the thread id does not. The coordinator and its members keep their names, an ACP session is known
by its thread, and nothing routes it to Claude-only tools.
Run: python3 -I skills/master-of-puppets/tests/test_provider_switch.py
Each test runs in its own empty MACHINE_LEASE_DIR; nothing touches the live state or sends a message."""
import importlib
import io
import os
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
ACP = {"T3CODE_THREAD_ID": "th-1", "__CFBundleIdentifier": "com.t3tools.t3code",
       "ANTIGRAVITY_SOURCE_METADATA": '{"tool": {"conversationId": "c-1"}}'}


class ProviderSwitch(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = os.path.join(self.tmp.name, "state")
        os.makedirs(os.environ["MACHINE_LEASE_DIR"])
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator", "puppet"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.c = importlib.import_module("coordinator")
        self.p = importlib.import_module("puppet")
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "a", "prs": [],
                                       "tool": "claude", "sessionId": "sa", "t3Thread": "th-1", "host": "t3-code"}
        roster["members"]["a"] = [{"name": "w", "tool": "claude", "sessionId": "s1", "status": "active",
                                   "t3Thread": "th-2", "host": "t3-code"}]
        self.m.save_roster(roster)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def run_cli(self, mod, env, *argv):
        self.m.RUN.env = env
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = mod.main(list(argv))
        return code, out.getvalue()

    def test_an_acp_session_is_known_by_its_thread(self):
        self.m.RUN.env = ACP
        self.assertEqual(self.m.session_or_none(), ("th-1", "antigravity"))
        self.assertEqual(self.m.detect_host(), "t3-code")
        self.m.RUN.env = {"T3CODE_THREAD_ID": "th-9"}
        self.assertEqual(self.m.session_or_none(), ("th-9", "t3"))

    def test_the_coordinator_keeps_its_name_after_a_switch(self):
        code, out = self.run_cli(self.c, ACP, "heartbeat", "--name", "a")
        self.assertEqual(code, 0, out)
        c = self.m.load_roster()["coordinators"]["a"]
        self.assertEqual((c["sessionId"], c["tool"], c["priorSessionId"]), ("th-1", "antigravity", "sa"))
        self.m.RUN.env = ACP
        self.assertEqual(self.m.caller(), "a")

    def test_a_member_keeps_its_name_and_gets_no_claude_route(self):
        env = dict(ACP, T3CODE_THREAD_ID="th-2")
        self.assertEqual(self.run_cli(self.p, env, "roster")[0], 0)
        m = self.m.load_roster()["members"]["a"][0]
        self.assertEqual((m["sessionId"], m["tool"]), ("th-2", "antigravity"))
        self.m.RUN.env = env
        rows = self.m.coordinator_routes("a", self.m.load_roster()["coordinators"]["a"])
        self.assertIn("t3_thread_send with threadId th-1", rows[0])
        self.assertFalse(any("SendMessage" in r for r in rows))
        self.assertIn("inbox only", self.m.deliver("w", "antigravity", "th-2", "hi"))

    def test_a_child_with_both_provider_ids_never_takes_the_thread(self):
        env = {"T3CODE_THREAD_ID": "th-1", "CLAUDE_CODE_SESSION_ID": "sa", "CODEX_THREAD_ID": "x-child"}
        self.m.RUN.env = env
        self.m.adopt_thread_identity()
        self.assertEqual(self.m.load_roster()["coordinators"]["a"]["sessionId"], "sa")


if __name__ == "__main__":
    unittest.main()
