"""Host sampling and lease admission with Linux and macOS inputs."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import server
import coordinator
import moplib


class HostMetrics(unittest.TestCase):
    def test_linux_dashboard(self):
        meminfo = ("MemTotal: 8388608 kB\nMemAvailable: 2097152 kB\n"
                   "SwapTotal: 2097152 kB\nSwapFree: 1048576 kB\n")
        ticks = iter(["cpu 10 0 0 30 10 0 0 0 1 0", "cpu 18 0 0 32 10 0 0 0 5 0"])

        def proc(name):
            if name == "stat":
                return next(ticks)
            return {"meminfo": meminfo, "vmstat": "pswpout 19\n"}[name]

        with patch.object(sys, "platform", "linux"), patch.object(moplib, "proc_text", proc), \
                patch.object(server.time, "sleep"), patch.object(server, "machine_config", return_value={}):
            sample, count = server.sample_host(9, 6)
            self.assertEqual(moplib.memory_free_pct(), 25)
        self.assertEqual(count, 19)
        expected = {"cpuPct": 80, "memUsedGiB": 6, "memTotalGiB": 8, "memFreePct": 25,
                    "swapTotalGiB": 2, "swapUsedGiB": 1, "swapoutsPer12s": 20}
        self.assertEqual({key: sample[key] for key in expected}, expected)

    def test_swap_gate(self):
        for counts, calm in [([0, 0, 0, 0], True), ([0, 200, 200, 200], False),
                             ([None] * 4, False), ([2, 1, 1, 1], False)]:
            with self.subTest(counts=counts), patch.object(coordinator, "swapouts", side_effect=counts), \
                    patch.object(coordinator, "nap"), patch.object(os, "getloadavg", return_value=(0, 0, 0)), \
                    patch.object(coordinator, "memory_free_pct", return_value=None), \
                    patch.object(coordinator, "load_machine", return_value=dict(moplib.MACHINE_DEFAULTS, diskFloorGiB=0)):
                self.assertEqual(coordinator.host_check()[0], calm)

    def test_mac_probes(self):
        with patch.object(sys, "platform", "darwin"), patch.object(moplib, "run", side_effect=[
                "Swapouts: 42.\n", "System-wide memory free percentage: 65%", str(8 * 2**30)]):
            self.assertEqual(moplib.swapouts(), 42)
            self.assertEqual(moplib.memory_free_pct(), 65)
            self.assertEqual(moplib.total_gib(), 8)


if __name__ == "__main__":
    unittest.main()
