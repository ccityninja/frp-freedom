"""Loopback-only, read-only phone triage. No firmware or lock operations."""

import json
import logging
import re
from contextlib import suppress
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

from app import usb_diagnostics

HOST = '127.0.0.1'
PORT = 8485
STATIC = Path(__file__).parent / 'static'
ASSETS = {
    '/': ('workbench.html', 'text/html; charset=utf-8'),
    '/workbench.js': ('workbench.js', 'text/javascript; charset=utf-8'),
}
ADB_NON_SYSTEM_STATES = {'offline', 'unauthorized', 'recovery', 'sideload', 'rescue', 'bootloader'}
BATTERY_STATES = {'2': 'charging', '3': 'discharging', '4': 'not charging', '5': 'full'}
BATTERY_TEMPERATURE_RANGE = range(-400, 1201)  # Tenths of a degree Celsius.
DF_MIN_COLUMNS = 6
BATTERY_FIELD = re.compile(
    r'^[ \t]*(level|scale|temperature|status):[ \t]*(-?[0-9]{1,6})[ \t]*$', re.M
)
TRANSPORT_FIELD = re.compile(r'transport_id:([1-9][0-9]{0,19})')


def _battery(text: str) -> dict | None:
    fields = dict(BATTERY_FIELD.findall(text))
    level, scale = int(fields.get('level', '-1')), int(fields.get('scale', '0'))
    temperature = int(fields.get('temperature', '-1000'))
    result = {
        'percent': round(100 * level / scale) if 0 <= level <= scale and scale else None,
        'temp_c': temperature / 10 if temperature in BATTERY_TEMPERATURE_RANGE else None,
        'state': BATTERY_STATES.get(fields.get('status', '')),
    }
    return result if any(value is not None for value in result.values()) else None


def _storage(text: str) -> dict | None:
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= DF_MIN_COLUMNS and fields[-1] == '/data' and all(
            re.fullmatch(r'[0-9]{1,16}', value) for value in fields[-5:-2]
        ):
            total, used, available = map(int, fields[-5:-2])
            if total > 0 and used + available <= total:
                return {'total_kib': total, 'available_kib': available}
    return None


def _health_target(status: str, rows: list[list[str]]) -> tuple[str, str | None]:
    if status != 'ok':
        return status, None
    if not rows:
        return 'no_device', None
    if len(rows) > 1:
        return 'multiple_devices', None
    row = rows[0]
    state = row[1] if len(row) > 1 else ''
    if state != 'device':
        return (state if state in ADB_NON_SYSTEM_STATES else 'unavailable'), None
    transports = [match[1] for item in row[2:] if (match := TRANSPORT_FIELD.fullmatch(item))]
    if len(transports) != 1:
        return 'unavailable', None
    return 'ready', transports[0]


def connection_report() -> dict:
    report, rows = usb_diagnostics.connection_snapshot()
    report['adb']['usb_transports'] = sum(
        any(field.startswith('usb:') for field in row[2:]) for row in rows
    )
    report['health_status'], _ = _health_target(report['adb']['status'], rows)
    return report


def health_report() -> dict:
    """Read only allowlisted metrics from one already authorized ADB transport."""
    status, transport = _health_target(*usb_diagnostics.adb_snapshot())
    return _read_metrics(transport) if transport is not None else {'status': status}


def _read_metrics(transport: str) -> dict:
    prefix = ('adb', '-t', transport, 'shell')
    battery_status, battery_text = usb_diagnostics._probe(*prefix, 'dumpsys', 'battery')
    storage_status, storage_text = usb_diagnostics._probe(*prefix, 'df', '-k', '/data')
    version_status, version_text = usb_diagnostics._probe(
        *prefix, 'getprop', 'ro.build.version.release',
    )
    battery = _battery(battery_text) if battery_status == 'ok' else None
    storage = _storage(storage_text) if storage_status == 'ok' else None
    version = version_text.strip()
    if version_status != 'ok' or not re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,3}){0,3}', version):
        version = None
    if battery is None and storage is None and version is None:
        return {'status': 'no_readings'}
    complete = (
        battery is not None and None not in battery.values()
        and storage is not None and version is not None
    )
    return {
        'status': 'ok' if complete else 'partial', 'battery': battery,
        'storage': storage, 'android_version': version,
    }


class Handler(BaseHTTPRequestHandler):
    timeout = 5
    probe_lock = Lock()

    def log_message(self, _format: str, *args: object) -> None:
        pass

    def _send(self, body: bytes, media_type: str, code: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(code)
        self.send_header('Content-Type', media_type)
        if code != HTTPStatus.NO_CONTENT:
            self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header(
            'Content-Security-Policy',
            "default-src 'none'; script-src 'self'; connect-src 'self'; "
            "style-src 'unsafe-inline'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'",
        )
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: dict, code: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(json.dumps(value).encode(), 'application/json', code)

    def _serve_asset(self, filename: str, media_type: str) -> None:
        try:
            body = (STATIC / filename).read_bytes()
        except FileNotFoundError:
            self._json({'error': 'asset not found'}, HTTPStatus.NOT_FOUND)
        except OSError:
            self._json({'error': 'asset could not be read'}, HTTPStatus.INTERNAL_SERVER_ERROR)
        else:
            self._send(body, media_type)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split('?', 1)[0]
        if path == '/index.html':
            path = '/'
        host = self.headers.get('Host')
        port = self.server.server_address[1]
        origin = self.headers.get('Origin')
        fetch_site = self.headers.get('Sec-Fetch-Site')
        if (host not in {f'{HOST}:{port}', f'localhost:{port}'}
                or origin not in {None, f'http://{host}'}
                or (path not in ASSETS and fetch_site not in {None, 'none', 'same-origin'})):
            self._json({'error': 'local origin only'}, HTTPStatus.FORBIDDEN)
            return
        if asset := ASSETS.get(path):
            self._serve_asset(*asset)
            return
        if path == '/favicon.ico':
            self._send(b'', 'image/x-icon', HTTPStatus.NO_CONTENT)
            return
        probe = {'/api/connection': connection_report, '/api/health': health_report}.get(path)
        if probe is None:
            self._json({'error': 'not found'}, HTTPStatus.NOT_FOUND)
        elif not self.probe_lock.acquire(blocking=False):
            self._json({'status': 'busy'}, HTTPStatus.SERVICE_UNAVAILABLE)
        else:
            try:
                self._json(probe())
            finally:
                self.probe_lock.release()

    def do_POST(self) -> None:  # noqa: N802
        self._json({'error': 'read-only service'}, HTTPStatus.METHOD_NOT_ALLOWED)


def make_server(port: int = PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), Handler)


if __name__ == '__main__':
    with make_server() as server:
        logging.getLogger(__name__).warning('Phone Repair Studio → http://%s:%d', HOST, PORT)
        with suppress(KeyboardInterrupt):
            server.serve_forever()
