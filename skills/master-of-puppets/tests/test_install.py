"""install refuses a skill copy whose commit is older than the installed one.
Run: python3 -I skills/master-of-puppets/tests/test_install.py
Each test runs in its own empty MACHINE_LEASE_DIR and a throwaway git repository."""
import argparse
import importlib
import io
import contextlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


class Rollback(unittest.TestCase):
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
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        self.git("init", "-q")
        self.old = self.commit("one")
        self.new = self.commit("two")

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def git(self, *argv):
        return subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *argv],
                              capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, text):
        with open(os.path.join(self.repo, "f"), "w") as f:
            f.write(text)
        self.git("add", "f")
        self.git("commit", "-q", "-m", text)
        return self.git("rev-parse", "HEAD")

    def installed(self, commit):
        self.m.write_json(self.m.SOURCE, {"path": "/elsewhere", "commit": commit})

    def test_older_copy_is_a_rollback(self):
        self.installed(self.new)
        self.git("checkout", "-q", "--detach", self.old)
        self.assertIn("older than the installed", self.c.rollback(self.repo))

    def test_same_or_newer_copy_passes(self):
        self.installed(self.new)
        self.assertIsNone(self.c.rollback(self.repo))
        self.installed(self.old)
        self.assertIsNone(self.c.rollback(self.repo))

    def test_no_record_or_no_git_passes(self):
        self.assertIsNone(self.c.rollback(self.repo))
        self.installed(self.new)
        self.assertIsNone(self.c.rollback(self.tmp.name))

    def test_install_refuses_with_exit_3_and_copies_nothing(self):
        self.installed(self.new)
        self.git("checkout", "-q", "--detach", self.old)
        real = os.path.realpath
        fake = os.path.join(self.repo, "coordinator.py")

        def must_not_run(*a, **k):
            raise AssertionError("install went past the refusal")
        buf = io.StringIO()
        with mock.patch.object(self.c.os.path, "realpath", lambda p: fake if p == self.c.__file__ else real(p)), \
                mock.patch.object(self.c, "install_files", must_not_run), \
                mock.patch.object(self.c, "restart_server", must_not_run), contextlib.redirect_stdout(buf):
            code = self.c.install_cmd(argparse.Namespace(allow_rollback=False))
        self.assertEqual(code, 3)
        self.assertIn("refused", buf.getvalue())
        self.assertEqual(self.m.read_json(self.m.SOURCE)["commit"], self.new)

if __name__ == "__main__":
    unittest.main()
