"""Project memory exchange through the coordinator commands, using temporary local state."""
from datetime import datetime
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CREATED = "2025-01-01T00:00:00+00:00"
EDITED = "2025-01-02T00:00:00+00:00"


def rule(identifier, text, **fields):
    return {"id": identifier, "kind": "rule", "text": text, "at": CREATED, "by": "writer", **fields}


class MemorySync(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source = root / "source" / "project"
        self.destination = root / "destination" / "project"
        self.source.mkdir(parents=True)
        self.destination.mkdir(parents=True)
        state = root / "state"
        state.mkdir()
        self.bundle = root / "exchange.json"

        contexts = ExitStack()
        self.addCleanup(contexts.close)
        contexts.enter_context(patch.dict(os.environ, MACHINE_LEASE_DIR=str(state)))
        contexts.enter_context(patch.object(sys, "path", [str(SCRIPTS), *sys.path]))
        contexts.enter_context(patch.dict(sys.modules))
        for module in ("moplib", "coordinator"):
            sys.modules.pop(module, None)
        self.memory = importlib.import_module("moplib")
        self.coordinator = importlib.import_module("coordinator")
        self.memory.RUN.env = {"MOP_ACTOR": "operator"}

    def command(self, *args, success=True):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            try:
                status = self.coordinator.main(["memory", *map(str, args)])
            except SystemExit as error:
                status = error.code
        if success:
            self.assertEqual(status, 0, output.getvalue())
        else:
            self.assertNotEqual(status, 0, output.getvalue())
        return output.getvalue()

    def store(self, project=None):
        return Path(self.memory.memory_path(project)[0])

    def seed(self, project, entries):
        path = self.store(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"entries": entries}))

    def test_project_round_trip_keeps_machine_and_merges_only_newer_rules(self):
        changed = rule("m-a00001", "Updated remotely", updatedAt=EDITED, updatedBy="editor")
        stale = rule("m-a00002", "Old remote text")
        tied = rule("m-a00003", "Different text at same instant", updatedAt="2025-01-02T01:00:00+01:00")
        added = rule("m-a00004", "New rule")
        machine = rule("m-b00001", "Keep this on this machine")
        note = rule("m-a00005", "Project note", kind="note")
        self.seed(self.source, [changed, stale, tied, added, note])
        self.seed(None, [machine])
        machine_bytes = self.store().read_bytes()
        bundle = json.loads(self.command("export", "--project-root", self.source))
        self.assertNotIn("machine", bundle)
        self.assertNotIn("prRules", bundle)
        portable = [changed, stale, tied, added]
        self.assertCountEqual([row["id"] for row in bundle["project"]], [row["id"] for row in portable])
        legacy = next(row for row in bundle["project"] if row["id"] == added["id"])
        exported_time = datetime.fromisoformat(legacy["updatedAt"].replace("Z", "+00:00"))
        self.assertEqual(exported_time, datetime.fromisoformat(CREATED))

        local_newer = rule(stale["id"], "Newer local text", updatedAt=EDITED)
        local_tie = rule(tied["id"], "Local text at same instant", updatedAt=EDITED)
        self.seed(self.destination, [
            rule(changed["id"], "Old local text"), local_newer, local_tie, note,
        ])
        self.bundle.write_text(json.dumps(bundle))
        for _ in range(2):
            self.command("import", "--project-root", self.destination, "--file", self.bundle)
        actual = json.loads(self.store(self.destination).read_text())["entries"]
        self.assertCountEqual(
            [(row["id"], row["text"]) for row in actual],
            [(row["id"], row["text"]) for row in (changed, local_newer, local_tie, added, note)],
        )
        updated = next(row for row in actual if row["id"] == changed["id"])
        self.assertEqual(updated["updatedBy"], "editor")
        self.assertEqual(self.store().read_bytes(), machine_bytes)

    def test_machine_pr_rules_merge_by_file_mtime(self):
        pr_rules = Path(self.memory.DIR) / "pr-rules.md"
        pr_rules.write_text("Remote review rules\n")
        transferred_mtime = 1735689600
        os.utime(pr_rules, (transferred_mtime, transferred_mtime))
        transferred_rule = rule("m-b00001", "Portable machine rule")
        self.seed(None, [transferred_rule])
        bundle = self.command("export")
        self.assertNotIn("project", json.loads(bundle))
        self.bundle.write_text(bundle)

        self.seed(None, [])
        pr_rules.write_text("Older local rules\n")
        os.utime(pr_rules, (transferred_mtime - 60, transferred_mtime - 60))
        self.command("import", "--file", self.bundle)
        self.assertEqual(pr_rules.read_text(), "Remote review rules\n")
        self.assertEqual(pr_rules.stat().st_mtime, transferred_mtime)
        entries = json.loads(self.store().read_text())["entries"]
        self.assertEqual([entry["text"] for entry in entries], [transferred_rule["text"]])

        pr_rules.write_text("Newer local rules\n")
        os.utime(pr_rules, (transferred_mtime + 60, transferred_mtime + 60))
        self.command("import", "--file", self.bundle)
        self.assertEqual(pr_rules.read_text(), "Newer local rules\n")

    def test_invalid_input_leaves_every_scope_untouched(self):
        machine = rule("m-a00001", "Machine rule")
        project = rule("m-b00001", "Project rule")
        self.seed(None, [machine])
        self.seed(self.source, [project])
        self.seed(self.destination, [rule("m-c00001", "Receiver rule")])
        pr_rules = Path(self.memory.DIR) / "pr-rules.md"
        pr_rules.write_text("Review rules\n")
        valid = json.loads(self.command("export", "--scope", "all", "--project-root", self.source))
        self.seed(None, [rule("m-d00001", "Receiver machine rule")])
        pr_rules.write_text("Receiver review rules\n")
        os.utime(pr_rules, (1735689600, 1735689600))
        tracked = [self.store(), self.store(self.destination), pr_rules]
        before = [path.read_bytes() for path in tracked]
        good = valid["project"][0]
        missing_id = {key: value for key, value in good.items() if key != "id"}
        for label, data in (
            ("bad JSON", "{"),
            ("unsupported version", json.dumps({**valid, "version": 999})),
            ("missing identifier", json.dumps({**valid, "project": [good, missing_id]})),
            ("malformed identifier", json.dumps({**valid, "project": [{**good, "id": "outside/project"}]})),
            ("invalid timestamp", json.dumps({**valid, "project": [{**good, "updatedAt": "yesterday"}]})),
            ("invalid text", json.dumps({**valid, "project": [{**good, "text": []}]})),
        ):
            with self.subTest(label=label):
                self.bundle.write_text(data)
                self.command("import", "--project-root", self.destination, "--file", self.bundle, success=False)
                self.assertEqual([path.read_bytes() for path in tracked], before)
        self.bundle.write_text(json.dumps(valid))
        self.command("import", "--file", self.bundle, success=False)
        self.assertEqual([path.read_bytes() for path in tracked], before)


if __name__ == "__main__":
    unittest.main()
