"""Exercise host diagnostics without a connected device or real subprocesses."""
import subprocess
from unittest.mock import patch

import pytest

from app import server

MAX_PROBE_SECONDS = 5


@pytest.mark.parametrize(
    ('adb_rows', 'expected'),
    [
        ('', {}),
        ('abc\tunauthorized usb:1-1\n', {'unauthorized': 1}),
        ('abc\toffline\nxyz\tdevice product:demo\n', {'offline': 1, 'authorized': 1}),
        ('abc\tno permissions (user not in group)\n', {'permission_denied': 1}),
    ],
)
def test_usb_report_counts_adb_states_without_publishing_identifiers(adb_rows, expected):
    outputs = {
        'lsusb': 'Bus 001 Device 001: ID 1d6b:0002 Linux Foundation\n'
                 'Bus 001 Device 002: ID 1234:5678 Example peripheral\n',
        'adb': 'List of devices attached\n' + adb_rows,
    }

    def run(argv, **kwargs):
        assert argv in [['lsusb'], ['adb', 'devices', '-l']]
        assert 0 < kwargs['timeout'] <= MAX_PROBE_SECONDS
        return subprocess.CompletedProcess(argv, 0, outputs[argv[0]], '')

    with patch('subprocess.run', side_effect=run):
        report = server.usb_report()

    assert report == {
        'usb': {'status': 'ok', 'non_root_hub_count': 1},
        'adb': {'status': 'ok', 'states': expected},
    }


def test_usb_probe_failures_are_distinct_from_empty_results():
    failures = [FileNotFoundError(), subprocess.TimeoutExpired('adb', MAX_PROBE_SECONDS)]
    with patch('subprocess.run', side_effect=failures):
        assert server.usb_report() == {
            'usb': {'status': 'missing', 'non_root_hub_count': None},
            'adb': {'status': 'timeout', 'states': {}},
        }


def test_adb_command_failure_is_reported_without_raw_output():
    with patch('subprocess.run', side_effect=[
        subprocess.CompletedProcess(['lsusb'], 0, '', ''),
        subprocess.CompletedProcess(['adb'], 1, '', 'local file path'),
    ]):
        assert server.usb_report() == {
            'usb': {'status': 'ok', 'non_root_hub_count': 0},
            'adb': {'status': 'error', 'states': {}},
        }
