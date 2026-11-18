"""Pool disk floors: a request's --min-free-gib, the clean after a create, and the health facts kept on a resource.
Run: python3 -I skills/master-of-puppets/tests/test_pool_floor.py
Each test runs in its own empty MACHINE_LEASE_DIR with fake pool commands; nothing touches the live state or a VM."""
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
CLASS = "VM"
# Each resource's free disk lives in $DISK/<name>; a clean raises it to $DISK/<name>.clean when that file exists.
HEALTH = 'echo "{\\"freeGiB\\": $(cat "$DISK/$MOP_RESOURCE"), \\"memAvailGiB\\": 8}"'
CLEAN = ('b=$(cat "$DISK/$MOP_RESOURCE"); [ -f "$DISK/$MOP_RESOURCE.clean" ] && cp "$DISK/$MOP_RESOURCE.clean" "$DISK/$MOP_RESOURCE"; '
         'echo "{\\"freeBeforeGiB\\": $b, \\"freeAfterGiB\\": $(cat "$DISK/$MOP_RESOURCE")}"')
CREATE = 'cp "$DISK/new" "$DISK/vm-new"; [ -f "$DISK/new.clean" ] && cp "$DISK/new.clean" "$DISK/vm-new.clean"; echo \'{"name": "vm-new"}\''


class Floor(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)  # the helpers read JSON with open() and no close
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = os.path.join(self.tmp.name, "state")
        os.makedirs(os.environ["MACHINE_LEASE_DIR"])
        self.disk = os.path.join(self.tmp.name, "disk")
        os.makedirs(self.disk)
        os.environ["DISK"] = self.disk
        sys.path.insert(0, SCRIPTS)
        for name in ("moplib", "coordinator"):
            sys.modules.pop(name, None)
        self.m = importlib.import_module("moplib")
        self.c = importlib.import_module("coordinator")
        self.m.RUN.env = {"MOP_ACTOR": "a", "DISK": self.disk}
        self.m.write_json(self.m.CONFIG, {"configured": True, "classes": {CLASS: {
            "description": "vm", "defaultGiB": 0, "maxMinutes": 0, "settle": {},
            "pool": {"create": CREATE, "health": HEALTH, "clean": CLEAN, "max": 5}}}})
        roster = self.m.load_roster()
        roster["coordinators"]["a"] = {"heartbeat": self.m.now().isoformat(), "focus": "test", "prs": []}
        self.m.save_roster(roster)
        self.tree = os.path.join(self.tmp.name, "wt")
        os.makedirs(self.tree)

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def disk_file(self, name, free, clean_to=None):
        with open(os.path.join(self.disk, name), "w") as f:
            f.write(str(free))
        if clean_to is not None:
            with open(os.path.join(self.disk, name + ".clean"), "w") as f:
                f.write(str(clean_to))

    def run_cmd(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.c.main(argv)
        return code, buf.getvalue()

    def resource(self, name, free, recorded=None, clean_to=None):
        self.disk_file(name, free, clean_to)
        self.assertEqual(self.run_cmd(["resource", "add", CLASS, "--name", name])[0], 0)
        if recorded is not None:
            self.edit(lambda st: self.m.find_resource(st, CLASS, name).update(freeGiB=recorded))

    def edit(self, fn):
        self.m.lock()
        try:
            state = self.m.load()
            fn(state)
            self.m.save(state, self.m.load_machine())
        finally:
            self.m.unlock()

    def request(self, entry_id, need):
        return self.run_cmd(["wait", CLASS, "--holder", "gw run", "--id", entry_id, "--minutes", "30",
                             "--worktree", self.tree, "--min-free-gib", str(need)])

    def acquire(self, entry_id):
        return self.run_cmd(["acquire", CLASS, "--holder", "gw run", "--id", entry_id, "--worktree", self.tree, "--minutes", "30"])

    def granted(self, entry_id):
        return next((h["resource"] for h in self.m.load()[CLASS] if h["id"] == entry_id), None)

    def events(self):
        return open(self.m.LOG).read()

    def test_pick_skips_a_resource_under_the_floor(self):
        self.resource("small", 12, recorded=12)
        self.resource("big", 45, recorded=45)
        self.request("a-1", 20)
        code, out = self.acquire("a-1")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.granted("a-1"), "big")
        self.assertEqual(self.m.find_resource(self.m.load(), CLASS, "big")["freeGiB"], 45)  # the grant's check is kept

    def test_resource_under_the_floor_is_cleaned_then_granted(self):
        self.resource("vm1", 12, clean_to=45)
        self.request("a-1", 20)
        code, out = self.acquire("a-1")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.granted("a-1"), "vm1")
        self.assertIn("under the request's floor", self.events())

    def test_new_resource_is_cleaned_after_create(self):
        self.disk_file("new", 12, clean_to=45)
        code, out = self.acquire("a-1")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.granted("a-1"), "vm-new")
        self.assertIn("(after create)", self.events())

    def test_new_resource_still_under_the_floor_waits_and_creates_no_more(self):
        self.disk_file("new", 12, clean_to=14)
        self.request("a-1", 20)
        code, out = self.acquire("a-1")
        self.assertEqual(code, 8, out)
        self.assertIsNone(self.granted("a-1"))
        res = self.m.find_resource(self.m.load(), CLASS, "vm-new")
        self.assertEqual((res["state"], res["freeGiB"]), ("free", 14))  # kept in the pool for other requests
        inbox = [json.loads(x) for x in open(self.m.INBOX) if x.strip()]
        self.assertTrue(any(r["message"].startswith("POOL-SHORT") for r in inbox))
        code, out = self.acquire("a-1")
        self.assertEqual(code, 3, out)
        self.assertIn("resources_short", out)
        self.assertEqual(len(self.m.load()["resources"][CLASS]), 1)  # no second create
        code, out = self.acquire("b-1")  # the short entry blocks nobody: a request with no floor behind it takes it
        self.assertEqual(code, 0, out)
        self.assertEqual(self.granted("b-1"), "vm-new")

        self.disk_file("vm-new", 40)  # b-1's run ends; the release check finds 40 GiB: a-1 is ready again
        self.run_cmd(["resource", "mark", CLASS, "--name", "vm-new", "--state", "free"])
        self.edit(lambda st: (st[CLASS].clear(), self.m.record_health(self.m.find_resource(st, CLASS, "vm-new"), {"freeGiB": 40}),
                              self.m.clear_short(st, CLASS, 40)))  # what the release's health check writes
        self.assertNotIn("createdShort", next(q for q in self.m.load()["queue"][CLASS] if q["id"] == "a-1"))
        code, out = self.acquire("a-1")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.granted("a-1"), "vm-new")


if __name__ == "__main__":
    unittest.main()
