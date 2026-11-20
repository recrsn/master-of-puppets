"""gh_http: a GitHub response cut off mid-read is retried once, then reported as status 0, never raised.
Run: python3 -I skills/master-of-puppets/tests/test_gh_http.py
Nothing reaches the network: urlopen is replaced."""
import http.client
import importlib
import os
import sys
import tempfile
import unittest
import warnings

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


class Body:
    status, headers = 200, {"ETag": "e1"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"[]"


class GhHttp(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore", ResourceWarning)
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MACHINE_LEASE_DIR"] = self.tmp.name
        sys.path.insert(0, SCRIPTS)
        sys.modules.pop("moplib", None)
        self.m = importlib.import_module("moplib")
        self.m._gh_token = "t"
        self.calls = 0

    def tearDown(self):
        sys.path.remove(SCRIPTS)
        self.tmp.cleanup()

    def urlopen(self, fails):
        def fake(req, timeout=None):
            self.calls += 1
            if self.calls <= fails:
                raise http.client.IncompleteRead(b"x" * 10, 99)
            return Body()
        self.m.urllib.request.urlopen = fake

    def test_one_cut_off_body_is_retried(self):
        self.urlopen(1)
        self.assertEqual(self.m.gh_http("https://example.com/x"), (200, "e1", "[]"))
        self.assertEqual(self.calls, 2)

    def test_two_cut_off_bodies_give_status_0(self):
        self.urlopen(2)
        status, etag, body = self.m.gh_http("https://example.com/x")
        self.assertEqual((status, etag), (0, None))
        self.assertIn("IncompleteRead", body)
        self.calls = 0
        self.assertIsNone(self.m.pr_scan("owner/repo", None, 0))  # one repo fails, not the whole cycle


if __name__ == "__main__":
    unittest.main()
