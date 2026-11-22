"""A scout's per-tick state is separate from its daily summary.
Run: python3 -I skills/master-of-puppets/tests/test_scout_state.py
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


class ScoutState(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # the helpers read JSON with open() and no close
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = os.path.join(self.tmp.name, "state")
        os.makedirs(os.environ["MACHINE_LEASE_DIR"])
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "puppet"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.p = importlib.import_module("puppet")
        self.m.RUN.env = {}  # no caller session unless a test sets one
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": []}
        roster["members"]["a"] = [{"name": "sc", "role": "scout", "status": "active", "tickMin": 15}]
        self.m.save_roster(roster)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def tick(self, *extra):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.p.main(["scout", "tick", "--coordinator", "a", "--name", "sc", *extra]), 0)
        return self.m.scout_state("sc")

    def as_session(self, sid):
        self.m.RUN.env = {"CLAUDE_CODE_SESSION_ID": sid}

    def test_two_sessions_ticking_as_one_scout_are_twins(self):
        roster = self.m.load_roster()
        roster["members"]["a"][0].update(sessionId="old", targetClass="prod", targets="api 5xx")
        self.m.save_roster(roster)
        self.as_session("old")
        self.assertNotIn("SESSION", self.scout("tick"))
        self.as_session("new")  # a provider handoff left the old session running
        out = self.scout("tick")
        self.assertIn("SESSION: this session (new) is not sc's roster session (old)", out)
        join = next(x.strip() for x in out.splitlines() if x.strip().startswith("SCOUT JOIN — sc — claude new"))
        sys.modules.pop("coordinator", None)
        self.assertEqual(importlib.import_module("coordinator").parse_join(join)["sessionId"], "new")  # ready to send
        self.assertIn("TWIN: session old also ticks as sc", out)
        self.m.RUN.env = {"MOP_ACTOR": "a"}
        sys.modules.pop("coordinator", None)
        c = importlib.import_module("coordinator")
        buf = io.StringIO()
        with redirect_stdout(buf):
            c.main(["member", "stale"])
        self.assertIn("sc scout ticking [TWIN: sessions new, old all tick", buf.getvalue())  # flags first
        self.assertIn("ticks from session new, not its roster session old", buf.getvalue())

    def test_a_recorded_report_keeps_a_scout_live_that_cannot_tick(self):
        roster = self.m.load_roster()
        m = roster["members"]["a"][0]
        m["joinedAt"] = (self.m.now() - self.m.dt.timedelta(hours=5)).isoformat()
        self.assertTrue(self.m.scout_stale(m, {})[0])
        m["updatedAt"] = self.m.now().isoformat()  # the coordinator ran member update for its message
        self.assertFalse(self.m.scout_stale(m, {})[0])

    def test_tick_state_replaces_itself_and_keeps_the_daily_summary(self):
        daily = self.tick("--summary", "day: 3 alerts, all resolved", "--state", "cursor 100")["summary"]
        st = self.tick("--state", "cursor 200")
        self.assertEqual(st["summary"], daily)
        self.assertEqual(st["state"]["text"], "cursor 200")
        st = self.tick()  # a tick with no state keeps the last one, with its own time
        self.assertEqual(st["state"]["text"], "cursor 200")
        self.assertEqual(st["summary"], daily)

    def scout(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.p.main(["scout", *argv[:1], "--coordinator", "a", "--name", "sc", *argv[1:]]), 0)
        return out.getvalue()

    def age(self, **fields):
        """Move times in the state file back by the given minutes."""
        st = self.m.scout_state("sc")
        back = lambda iso, mins: (self.m.dt.datetime.fromisoformat(iso) - self.m.dt.timedelta(minutes=mins)).isoformat()
        if "tick" in fields:
            st["lastTick"] = back(st["lastTick"], fields["tick"])
            if st.get("tickAt"):
                st["tickAt"] = back(st["tickAt"], fields["tick"])
        if "seen" in fields:
            for a in st["openAlerts"]:
                a["lastSeen"] = back(a["lastSeen"], fields["seen"])
        if "resolved" in fields:
            st["resolved"] = {f: back(t, fields["resolved"]) for f, t in st.get("resolved", {}).items()}
        self.m.write_json(self.m.scout_path("sc"), st)

    def test_a_late_tick_says_so_and_names_the_cursor(self):
        self.scout("tick", "--state", "cursor 100")
        self.assertNotIn("LATE", self.scout("tick"))
        self.age(tick=45)
        out = self.scout("tick", "--state", "cursor 300")  # the new cursor must not hide the old one
        self.assertIn("LATE 45m", out)
        self.assertIn("cursor then was: cursor 100", out)
        self.assertIn("LATE 45m", self.scout("tick"))  # a plain tick does not clear it
        out = self.scout("tick", "--reread")
        self.assertIn("read again", out)
        self.assertNotIn("EARLY", out)  # the reread closes this turn's LATE tick: it is no catch-up run
        self.assertNotIn("LATE", self.scout("tick"))

    def test_a_late_tick_that_starts_with_an_alert_still_says_late(self):
        self.scout("tick", "--state", "cursor 100")
        self.age(tick=45)
        self.assertNotIn("LATE", self.scout("alert", "--fingerprint", "f1", "--severity", "P2", "--text", "x"))
        self.assertIn("LATE 45m", self.scout("tick"))

    def test_an_alert_resolved_two_ticks_ago_reopens_as_a_flap(self):
        alert = ("alert", "--fingerprint", "f1", "--severity", "P2", "--text", "x")
        self.assertIn("NEW", self.scout(*alert))
        self.assertIn("NOT YET", self.scout("resolve", "--fingerprint", "f1"))  # seen just now: not 2 clean ticks
        self.age(seen=28)  # a scheduled tick starts a little early: 2 ticks less the slack counts
        self.assertIn("RESOLVED", self.scout("resolve", "--fingerprint", "f1"))
        self.assertIn("REOPENED", self.scout(*alert))
        self.age(seen=31)
        self.scout("resolve", "--fingerprint", "f1")
        self.age(resolved=61)  # more than 4 tick lengths of 15 min: a new alert again
        self.assertIn("NEW", self.scout(*alert))

    def test_a_tick_lists_alerts_not_seen_for_a_day(self):
        self.scout("alert", "--fingerprint", "old", "--severity", "P2", "--text", "x")
        self.assertNotIn("24 h", self.scout("tick"))
        self.age(seen=25 * 60)
        out = self.scout("tick")
        self.assertIn("OLD×1", out.splitlines()[0].split("ACT:")[1])  # on line 1: a scout that cuts the output still sees it
        self.assertIn("1 not seen for 24 h", out)
        self.assertIn("\n  OLD old", out)
        self.assertNotIn("UNHANDLED", out)  # the first tick with the tag
        st = self.m.read_json(self.m.scout_path("sc"))
        st["actSince"]["OLD"] = (self.m.now() - self.m.dt.timedelta(minutes=31)).isoformat()  # 2 ticks ago
        self.m.write_json(self.m.scout_path("sc"), st)
        out = self.scout("tick")
        self.assertIn("UNHANDLED", out.splitlines()[0])
        self.assertIn("UNHANDLED OLD since", out)
        self.scout("resolve", "--fingerprint", "old")
        self.assertNotIn("UNHANDLED", self.scout("tick"))  # acted on: the tag and its age are gone


    def test_a_second_tick_soon_after_the_first_is_early(self):
        self.assertNotIn("EARLY", self.scout("tick"))
        self.scout("alert", "--fingerprint", "f1", "--severity", "P2", "--text", "x")  # moves lastTick, not tickAt
        out = self.scout("tick")
        self.assertIn("EARLY", out.splitlines()[0])
        self.assertIn("send nothing", out)
        st = self.m.read_json(self.m.scout_path("sc"))
        st["tickAt"] = (self.m.now() - self.m.dt.timedelta(minutes=10)).isoformat()  # more than half of 15 min
        self.m.write_json(self.m.scout_path("sc"), st)
        self.assertNotIn("EARLY", self.scout("tick"))

    def test_a_note_adds_to_the_state_without_a_tick(self):
        self.scout("tick", "--state", "cursor 100")
        tick_at = self.m.scout_state("sc")["tickAt"]
        out = self.scout("note", "--text", "REGISTER #7")
        self.assertIn("cursor 100 | REGISTER #7", out)
        st = self.m.scout_state("sc")
        self.assertEqual((st["tickAt"], st["state"]["text"]), (tick_at, "cursor 100 | REGISTER #7"))
        self.assertNotIn("EARLY", out)

if __name__ == "__main__":
    unittest.main()
