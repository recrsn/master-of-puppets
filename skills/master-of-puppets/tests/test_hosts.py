"""The host (where a session runs), not the provider, decides the send tool: detect_host reads the caller's
environment, members and coordinators record their host, and routes list only the tools the caller has.
Run: python3 -I skills/master-of-puppets/tests/test_hosts.py
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

T3_CLAUDE = {"CLAUDE_CODE_SESSION_ID": "s1", "CLAUDE_CODE_ENTRYPOINT": "t3-code", "T3CODE_THREAD_ID": "th-1"}
T3_CODEX = {"CODEX_THREAD_ID": "x1", "__CFBundleIdentifier": "com.t3tools.t3code",
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "T3 Code"}
CLAUDE_DESKTOP = {"CLAUDE_CODE_SESSION_ID": "s1", "CLAUDE_CODE_ENTRYPOINT": "claude-desktop"}
CLAUDE_CLI = {"CLAUDE_CODE_SESSION_ID": "s1", "CLAUDE_CODE_ENTRYPOINT": "cli"}
CODEX_DESKTOP = {"CODEX_THREAD_ID": "x1", "__CFBundleIdentifier": "com.openai.codex"}
CODEX_CLI = {"CODEX_THREAD_ID": "x1", "__CFBundleIdentifier": "com.example.terminal"}


class Hosts(unittest.TestCase):
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

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def host(self, env):
        self.m.RUN.env = env
        return self.m.detect_host()

    def routes(self, env, target):
        self.m.RUN.env = env
        return self.m.routes_to(target, "inbox")

    def test_each_host_is_detected_from_its_environment(self):
        self.assertEqual(self.host(T3_CLAUDE), "t3-code")
        self.assertEqual(self.host(T3_CODEX), "t3-code")
        self.assertEqual(self.host(CLAUDE_DESKTOP), "claude-desktop")
        self.assertEqual(self.host(CLAUDE_CLI), "claude-code")
        self.assertEqual(self.host(CODEX_DESKTOP), "codex-desktop")
        self.assertEqual(self.host(CODEX_CLI), "unknown")  # a Codex CLI shows no positive sign: host --set
        self.assertEqual(self.host({}), "unknown")
        # a Codex thread started from a Claude Desktop session inherits its entrypoint: Codex markers count
        self.assertEqual(self.host(dict(CODEX_DESKTOP, CLAUDE_CODE_ENTRYPOINT="claude-desktop")), "codex-desktop")

    def test_routes_name_only_the_callers_send_tools(self):
        t3_codex_coord = {"tool": "codex", "sessionId": "x9", "host": "t3-code", "t3Thread": "th-9"}
        claude_coord = {"tool": "claude", "sessionId": "s9", "host": "claude-desktop"}
        desktop_codex = {"tool": "codex", "sessionId": "x9", "host": "codex-desktop"}
        r = self.routes(T3_CODEX, t3_codex_coord)
        self.assertIn("t3_thread_send with threadId th-9", r[0])
        self.assertFalse(any("SendMessage" in x or "send_message_to_thread" in x for x in r))
        r = self.routes(T3_CLAUDE, claude_coord)  # Claude in T3 Code reaches a Claude Desktop session
        self.assertIn("SendMessage to s9", r[0])
        self.assertEqual(self.routes(T3_CODEX, claude_coord), ["inbox"])  # no shared tool: the inbox only
        self.assertEqual(self.routes(CLAUDE_DESKTOP, desktop_codex), ["inbox"])
        self.assertIn("send_message_to_thread with threadId x9", self.routes(CODEX_DESKTOP, desktop_codex)[0])
        self.assertEqual(self.routes(CODEX_DESKTOP, t3_codex_coord), ["inbox"])  # another app's thread
        r = self.routes(T3_CLAUDE, {"tool": "codex", "sessionId": "x9", "host": "t3-code"})  # thread id not known
        self.assertIn("t3_thread_search", r[0])
        r = self.routes(T3_CLAUDE, {"tool": "codex", "sessionId": "x9"})  # a member whose host is not recorded yet
        self.assertIn("t3_thread_search", r[0])

    def test_coordinator_and_member_record_their_host(self):
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "a", "prs": [],
                                       "tool": "codex", "sessionId": "x1"}
        roster["members"]["a"] = [{"name": "w", "tool": "claude", "sessionId": "s1", "status": "active"}]
        self.m.save_roster(roster)
        self.m.RUN.env = CODEX_DESKTOP
        with redirect_stdout(io.StringIO()):
            self.c.main(["heartbeat", "--name", "a"])
        self.assertEqual(self.m.load_roster()["coordinators"]["a"]["host"], "codex-desktop")
        self.m.RUN.env = CLAUDE_DESKTOP
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.p.main(["host"]), 0)
        self.assertIn("host claude-desktop", out.getvalue())
        self.assertIn("references/hosts/claude-desktop.md", out.getvalue())
        self.assertEqual(self.m.load_roster()["members"]["a"][0]["host"], "claude-desktop")
        # the Codex Desktop coordinator and the Claude Desktop member share no app tool
        self.m.RUN.env = CODEX_DESKTOP
        self.assertIn("No shared route", self.c.native_route(self.m.load_roster()["members"]["a"][0]))
        # a thinner environment never erases a recorded host
        self.m.RUN.env = {"CLAUDE_CODE_SESSION_ID": "s1"}
        with redirect_stdout(io.StringIO()):
            self.p.main(["roster"])
        self.assertEqual(self.m.load_roster()["members"]["a"][0]["host"], "claude-desktop")

    def test_a_cli_session_states_its_host(self):
        roster = self.m.load_roster()
        roster["members"]["a"] = [{"name": "w", "tool": "codex", "sessionId": "x1", "status": "active"}]
        self.m.save_roster(roster)
        self.m.RUN.env = CODEX_CLI
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.p.main(["host", "--set", "codex-cli"]), 0)
        self.assertIn("host codex-cli", out.getvalue())
        self.assertIn("codex queue --thread x9", self.routes(CODEX_CLI, {"tool": "codex", "sessionId": "x9"})[0])


if __name__ == "__main__":
    unittest.main()
