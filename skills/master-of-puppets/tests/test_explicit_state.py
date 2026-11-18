"""Explicit state instead of guesses: session processes in drain, the expiry notice to the holder, a pin to a
resource that left the pool, and the roster compared with the app's live sessions.
Run: python3 -I skills/master-of-puppets/tests/test_explicit_state.py
Each test runs in its own empty MACHINE_LEASE_DIR; nothing touches the live state, sends a message or reads the app."""
import datetime as dt
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import warnings
from contextlib import redirect_stdout

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


class Base(unittest.TestCase):
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
        self.told = []
        self.c.tell_member = lambda sender, coord, name, text: self.told.append((name, text)) or f"{name}: test"
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": []}
        self.m.save_roster(roster)
        self.tree = os.path.join(self.tmp.name, "wt")
        os.makedirs(self.tree)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def run_cmd(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.c.main(argv)
        return code, buf.getvalue()

    def edit(self, fn):
        self.m.lock()
        try:
            state = self.m.load()
            fn(state)
            self.m.save(state, self.m.load_machine())
        finally:
            self.m.unlock()


class SessionProcesses(Base):
    def test_agent_helpers_are_skipped_and_shell_runs_count(self):
        table = "\n".join([
            "100 1 100 /Applications/Claude.app/claude",  # the agent program
            "101 100 101 /opt/homebrew/bin/uv",           # its MCP launcher
            "102 101 101 /usr/bin/python3",               # the MCP server, through the launcher
            "103 100 103 /bin/zsh",                       # a shell command of the agent
            "104 103 103 /usr/bin/make",                  # a run: counts
            "105 104 103 /usr/bin/node",                  # deeper in the run: counts
        ])
        self.m.run = lambda cmd: table if cmd[0] == "ps" else ""
        self.m.RUN.env = {"MOP_ACTOR": "a", "MOP_CLIENT_PID": "999", "MOP_CLIENT_PGID": "999"}
        skip = self.m.session_pids()
        self.assertTrue({"100", "101", "102", "103"} <= skip)
        self.assertFalse({"104", "105"} & skip)


class Expiry(Base):
    def setUp(self):
        super().setUp()
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {"BUILD": dict(self.m.DEFAULT_REGISTRY["BUILD"])}})

    def hold(self, minutes_ago):
        t = self.m.now()
        self.edit(lambda st: st["BUILD"].append({
            "coordinator": "a", "holder": "gw build", "id": "a-q-gw-1", "worktree": self.tree, "project": "p",
            "gib": 1, "cpus": 1, "commands": "make", "grantedAt": (t - dt.timedelta(minutes=30)).isoformat(),
            "expiresAt": (t - dt.timedelta(minutes=minutes_ago)).isoformat()}))

    def test_holder_is_told_once_per_expiry(self):
        self.hold(1)
        self.c.expiry_notice("BUILD")
        self.c.expiry_notice("BUILD")
        self.assertEqual(len(self.told), 1)
        self.assertEqual(self.told[0][0], "gw")
        self.assertIn("LEASE EXPIRED BUILD a-q-gw-1", self.told[0][1])
        self.assertIn("puppet.py extend BUILD", self.told[0][1])
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.c.round_leases("a")
        self.assertIn("holder told at", buf.getvalue())

        later = (self.m.now() - dt.timedelta(seconds=1)).isoformat()  # extended, and that expiry passed too
        self.edit(lambda st: st["BUILD"][0].update(expiresAt=later))
        self.c.expiry_notice("BUILD")
        self.assertEqual(len(self.told), 2)

    def test_live_lease_is_not_told(self):
        self.hold(-10)  # expires in 10 minutes
        self.c.expiry_notice("BUILD")
        self.assertEqual(self.told, [])


class PinnedResource(Base):
    def test_pin_to_a_resource_that_left_the_pool_is_dropped(self):
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {"VM": {
            "description": "vm", "defaultGiB": 0, "maxMinutes": 0, "settle": {}, "pool": {"max": 5}}}})
        self.assertEqual(self.run_cmd(["resource", "add", "VM", "--name", "vm2"])[0], 0)
        self.run_cmd(["wait", "VM", "--holder", "gw run", "--id", "a-q-gw-1", "--minutes", "30",
                      "--worktree", self.tree, "--resource", "vm1"])
        code, out = self.run_cmd(["acquire", "VM", "--holder", "gw run", "--id", "a-q-gw-1", "--worktree", self.tree, "--minutes", "30"])
        self.assertEqual(code, 0, out)
        self.assertEqual(next(h["resource"] for h in self.m.load()["VM"]), "vm2")
        inbox = [json.loads(x) for x in open(self.m.INBOX) if x.strip()]
        self.assertTrue(any(r["message"].startswith("PIN-DROPPED VM a-q-gw-1") and r.get("to") == "a" for r in inbox))


class Sessions(Base):
    def member(self, name, sid, worktree=None, prs=None):
        roster = self.m.load_roster()
        roster["members"].setdefault("a", []).append({"name": name, "tool": "claude", "sessionId": sid, "status": "active",
                                                      "worktree": worktree or self.tree, "prs": prs or [], "repo": "o/r",
                                                      "task": "the task"})
        self.m.save_roster(roster)

    def test_report_compares_the_roster_with_live_sessions(self):
        subprocess.run(["git", "init", "-q", self.tree], check=True)
        with open(os.path.join(self.tree, "x"), "w") as f:
            f.write("x")
        idle, gone, new, other = ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222",
                                  "33333333-3333-3333-3333-333333333333", "44444444-4444-4444-4444-444444444444")
        moved = os.path.join(self.tmp.name, "moved")
        os.makedirs(moved)
        self.member("busy-one", idle)
        self.member("gone-one", gone, worktree=moved)
        self.member("app-id", "local_abc")
        self.c.app_sessions = lambda: {
            idle: {"sessionId": idle, "status": "idle", "cwd": self.tree, "name": "busy-one"},
            new: {"sessionId": new, "status": "busy", "cwd": moved, "name": "gone-one again"},
            other: {"sessionId": other, "status": "idle", "cwd": "/elsewhere", "name": "other"}}
        lines, untracked = self.c.session_report("a")
        text = "\n".join(lines)
        self.assertIn("IDLE-WITH-WORK busy-one: 1 uncommitted paths", text)
        self.assertIn(f"STALE gone-one: session 22222222 is not running; the one untracked session in its worktree is {new}", text)
        self.assertIn("NOT-CHECKED app-id", text)
        self.assertEqual(sorted(x["sessionId"] for x in untracked), [new, other])
        self.assertEqual(self.told, [])  # no message without send
        self.c.session_report("a", send=True)
        self.assertEqual([n for n, _ in self.told], ["busy-one"])


if __name__ == "__main__":
    unittest.main()
