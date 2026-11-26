"""Read-only phone workbench behavior at ADB and HTTP boundaries."""

import json
import subprocess
from http import HTTPStatus
from http.client import HTTPConnection
from threading import Thread
from unittest.mock import patch

import pytest

from app import workbench

MAX_PROBE_TIMEOUT = 5
_DEVICE = 'do-not-export device usb:1-3 model:Demo transport_id:17'


def test_health_pins_one_authorized_transport_and_returns_only_metrics():
    prefix = ('adb', '-t', '17', 'shell')
    replies = {
        ('adb', 'devices', '-l'): 'List of devices attached\n' + _DEVICE,
        (*prefix, 'dumpsys', 'battery'): (
            'Current Battery Service state:\n  level: 64\n  scale: 100\n'
            '  temperature: 325\n  USB powered: true\n  status: 2\n  junk: do-not-export\n'
        ),
        (*prefix, 'df', '-k', '/data'): (
            'Filesystem 1K-blocks Used Available Use% Mounted on\n'
            '/dev/block/dm-1 100000 60000 40000 60% /data\n'
        ),
        (*prefix, 'getprop', 'ro.build.version.release'): '16\n',
    }

    with patch('app.usb_diagnostics._probe', side_effect=lambda *args: ('ok', replies[args])):
        report = workbench.health_report()
    assert report == {
        'status': 'ok', 'battery': {'percent': 64, 'temp_c': 32.5, 'state': 'charging'},
        'storage': {'total_kib': 100000, 'available_kib': 40000}, 'android_version': '16',
    }
    assert 'do-not-export' not in json.dumps(report)


@pytest.mark.parametrize(('status', 'rows', 'expected'), [
    ('ok', '', 'no_device'),
    ('ok', 'serial unauthorized usb:1-3 transport_id:18', 'unauthorized'),
    ('ok', 'serial offline transport_id:18', 'offline'),
    ('ok', 'serial recovery transport_id:18', 'recovery'),
    ('ok', 'serial sideload transport_id:18', 'sideload'),
    ('ok', 'serial rescue transport_id:18', 'rescue'),
    ('ok', 'serial bootloader transport_id:18', 'bootloader'),
    ('ok', 'serial no permissions (user not in plugdev)', 'unavailable'),
    ('ok', _DEVICE + '\nother unauthorized transport_id:18', 'multiple_devices'),
    ('ok', 'serial device transport_id:-a', 'unavailable'),
    ('timeout', '', 'timeout'),
    ('missing', '', 'missing'),
])
def test_no_device_commands_without_an_unambiguous_authorized_transport(status, rows, expected):
    def reply(*args):
        assert args == ('adb', 'devices', '-l')
        return status, 'List of devices attached\n' + rows if status == 'ok' else ''

    with patch('app.usb_diagnostics._probe', side_effect=reply):
        assert workbench.health_report() == {'status': expected}


def test_health_preserves_unknown_metrics_and_handles_non_100_battery_scale():
    def reply(*args):
        command = args[4:]
        if args == ('adb', 'devices', '-l'):
            return 'ok', 'List of devices attached\n' + _DEVICE
        if command == ('dumpsys', 'battery'):
            return 'ok', 'level: 120\nscale: 200\ntemperature: invalid\nstatus: 7\n'
        if command == ('df', '-k', '/data'):
            return 'ok', '/dev/example 100 99 999 99% /data\n'
        assert command == ('getprop', 'ro.build.version.release')
        return 'timeout', ''

    with patch('app.usb_diagnostics._probe', side_effect=reply):
        assert workbench.health_report() == {
            'status': 'partial', 'battery': {'percent': 60, 'temp_c': None, 'state': None},
            'storage': None, 'android_version': None,
        }


def test_health_distinguishes_no_readings_from_a_partial_snapshot():
    replies = {
        ('adb', 'devices', '-l'): ('ok', 'List of devices attached\n' + _DEVICE),
        ('adb', '-t', '17', 'shell', 'dumpsys', 'battery'): ('error', ''),
        ('adb', '-t', '17', 'shell', 'df', '-k', '/data'): ('timeout', ''),
        ('adb', '-t', '17', 'shell', 'getprop', 'ro.build.version.release'): ('ok', '\n'),
    }
    with patch('app.usb_diagnostics._probe', side_effect=lambda *args: replies[args]):
        assert workbench.health_report() == {'status': 'no_readings'}


@pytest.fixture
def workbench_request():
    with workbench.make_server(port=0) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = HTTPConnection('127.0.0.1', server.server_port, timeout=6)

        def request(method, path, **headers):
            conn.request(method, path, headers=headers)
            response = conn.getresponse()
            return response.status, response.read(), dict(response.getheaders())

        try:
            yield request
        finally:
            conn.close()
            server.shutdown()
            thread.join(timeout=6)


def test_http_workbench_is_local_read_only_and_does_not_expose_executor(workbench_request):
    request = workbench_request

    def run(argv, **kwargs):
        assert argv == ['adb', 'devices', '-l']
        assert kwargs['timeout'] <= MAX_PROBE_TIMEOUT
        return subprocess.CompletedProcess(argv, 0, 'List of devices attached\n\n', '')

    assert request('GET', '/', **{'Sec-Fetch-Site': 'cross-site'})[0] == HTTPStatus.OK
    assert request('GET', '/workbench.js')[0] == HTTPStatus.OK
    assert request('GET', '/api/health', Host='other.example')[0] == HTTPStatus.FORBIDDEN
    for headers in ({'Origin': 'http://other.example'}, {'Sec-Fetch-Site': 'cross-site'}):
        assert request('GET', '/api/health?view=1', **headers)[0] == HTTPStatus.FORBIDDEN
    assert request('POST', '/api/execute')[0] == HTTPStatus.METHOD_NOT_ALLOWED
    assert request('GET', '/api/execute')[0] == HTTPStatus.NOT_FOUND
    with patch('app.usb_diagnostics.subprocess.run', side_effect=run):
        status, body, headers = request('GET', '/api/health')
    assert status == HTTPStatus.OK
    assert json.loads(body) == {'status': 'no_device'}
    assert headers['Cache-Control'] == 'no-store'


def test_workbench_bookmarks_and_security_headers(workbench_request):
    status, body, headers = workbench_request('GET', '/?view=repair')
    assert status == HTTPStatus.OK
    assert b'<h1>Phone Repair Studio</h1>' in body
    assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['Referrer-Policy'] == 'no-referrer'
    assert workbench_request('GET', '/index.html')[1] == body
    assert workbench_request('GET', '/favicon.ico')[:2] == (HTTPStatus.NO_CONTENT, b'')


def test_missing_workbench_asset_returns_http_error(workbench_request, tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, 'STATIC', tmp_path)
    status, body, _ = workbench_request('GET', '/workbench.js')
    assert status == HTTPStatus.NOT_FOUND
    assert json.loads(body) == {'error': 'asset not found'}


def test_connection_route_returns_aggregate_counts(workbench_request):
    replies = {
        ('adb', 'devices', '-l'): 'List of devices attached\n' + _DEVICE,
        ('lsusb',): 'Bus 001 Device 001: ID 1d6b:0002 hub\nBus 001 Device 002: ID abcd:1234 test\n',
    }

    def run(argv, **kwargs):
        assert kwargs['timeout'] <= MAX_PROBE_TIMEOUT
        return subprocess.CompletedProcess(argv, 0, replies[tuple(argv)], '')

    with patch('app.usb_diagnostics.subprocess.run', side_effect=run):
        status, body, _ = workbench_request('GET', '/api/connection')
    assert status == HTTPStatus.OK
    assert json.loads(body) == {
        'usb': {'status': 'ok', 'non_root_hub_count': 1},
        'adb': {'status': 'ok', 'states': {'authorized': 1}, 'usb_transports': 1},
        'health_status': 'ready',
    }
    assert b'do-not-export' not in body
    assert b'abcd:1234' not in body


@pytest.mark.parametrize(('rows', 'usb_transports', 'health_status'), [
    ('', 0, 'no_device'),
    ('private unauthorized usb:1-2 transport_id:3', 1, 'unauthorized'),
    ('private recovery usb:1-2 transport_id:3', 1, 'recovery'),
    ('private device usb:1-2 transport_id:invalid', 1, 'unavailable'),
    ('private device transport_id:3', 0, 'ready'),
    (_DEVICE + '\nprivate device transport_id:3', 1, 'multiple_devices'),
])
def test_connection_advertises_health_availability_without_running_health_commands(
    workbench_request, rows, usb_transports, health_status,
):
    replies = {
        ('adb', 'devices', '-l'): f'List of devices attached\n{rows}\n',
        ('lsusb',): 'Bus 001 Device 002: ID abcd:1234 peripheral\n',
    }

    def run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, replies[tuple(argv)], '')

    with patch('app.usb_diagnostics.subprocess.run', side_effect=run):
        status, body, _ = workbench_request('GET', '/api/connection')
    assert status == HTTPStatus.OK
    report = json.loads(body)
    assert report['adb']['usb_transports'] == usb_transports
    assert report['health_status'] == health_status
    assert b'private' not in body


def test_connection_poll_rejects_a_cross_site_caller_before_probing(workbench_request):
    with patch('app.usb_diagnostics.subprocess.run', side_effect=AssertionError):
        status, _, _ = workbench_request('GET', '/api/connection', Origin='http://other.example')
    assert status == HTTPStatus.FORBIDDEN


def test_connection_route_reports_busy_without_running_another_probe(workbench_request):
    with (
        workbench.Handler.probe_lock,
        patch('app.usb_diagnostics.subprocess.run', side_effect=AssertionError),
    ):
        status, body, _ = workbench_request('GET', '/api/connection')
    assert status == HTTPStatus.SERVICE_UNAVAILABLE
    assert json.loads(body) == {'status': 'busy'}
