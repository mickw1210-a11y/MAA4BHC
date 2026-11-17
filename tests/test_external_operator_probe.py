import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.external_operator_probe import (
    OperatorProbeState,
    OperatorProbeUnknown,
    parse_netstat_tcp_snapshot,
    scan_local_adb_clients,
)


class NetstatSnapshotParserTests(unittest.TestCase):
    def test_finds_established_ipv4_adb_clients(self):
        output = """Active Connections
  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:54001        127.0.0.1:5037         ESTABLISHED     1234
  TCP    127.0.0.1:5037         0.0.0.0:0              LISTENING       888
  TCP    127.0.0.1:54002        127.0.0.1:80           ESTABLISHED     4444
  TCP    127.0.0.1:54003        127.0.0.1:80           TIME_WAIT       0
"""
        self.assertEqual(parse_netstat_tcp_snapshot(output), (1234,))

    def test_finds_ipv6_loopback_client(self):
        output = "TCP [::1]:54001 [::1]:5037 ESTABLISHED 4567"
        self.assertEqual(parse_netstat_tcp_snapshot(output), (4567,))

    def test_deduplicates_and_rejects_malformed_tcp_rows(self):
        output = """TCP 127.0.0.1:54001 127.0.0.1:5037 ESTABLISHED 1234
TCP 127.0.0.1:54002 127.0.0.1:5037 ESTABLISHED 1234
"""
        self.assertEqual(parse_netstat_tcp_snapshot(output), (1234,))
        with self.assertRaises(OperatorProbeUnknown):
            parse_netstat_tcp_snapshot("TCP 127.0.0.1:54001 127.0.0.1:5037 ESTABLISHED")
        with self.assertRaises(OperatorProbeUnknown):
            parse_netstat_tcp_snapshot("unexpected output")
        with self.assertRaisesRegex(OperatorProbeUnknown, "进程ID不可见"):
            parse_netstat_tcp_snapshot("TCP 127.0.0.1:54001 127.0.0.1:5037 ESTABLISHED 0")


class ExternalOperatorScanTests(unittest.TestCase):
    def test_unknown_when_platform_snapshot_is_unavailable(self):
        with patch("app.external_operator_probe.IS_WINDOWS", False):
            report = scan_local_adb_clients()
        self.assertIs(report.state, OperatorProbeState.UNKNOWN)
        self.assertTrue(report.reason)

    def test_marks_only_unregistered_adb_client_pids_as_conflicts(self):
        output = "TCP 127.0.0.1:54001 127.0.0.1:5037 ESTABLISHED 101\nTCP 127.0.0.1:54002 127.0.0.1:5037 ESTABLISHED 202\n"
        completed = SimpleNamespace(returncode=0, stdout=output)
        with patch("app.external_operator_probe.IS_WINDOWS", True), \
                patch("app.external_operator_probe._netstat_path", return_value=Path("C:/Windows/System32/netstat.exe")), \
                patch("app.external_operator_probe.subprocess.run", return_value=completed) as run:
            report = scan_local_adb_clients(trusted_process_ids={101})
        self.assertIs(report.state, OperatorProbeState.CONFLICT)
        self.assertEqual(report.observed_adb_client_pids, (101, 202))
        self.assertEqual(report.external_adb_client_pids, (202,))
        self.assertEqual(run.call_args.args[0][-3:], ["-ano", "-p", "tcp"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_netstat_failure_never_reports_clear(self):
        completed = SimpleNamespace(returncode=1, stdout="")
        with patch("app.external_operator_probe.IS_WINDOWS", True), \
                patch("app.external_operator_probe._netstat_path", return_value=Path("C:/Windows/System32/netstat.exe")), \
                patch("app.external_operator_probe.subprocess.run", return_value=completed):
            report = scan_local_adb_clients()
        self.assertIs(report.state, OperatorProbeState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
