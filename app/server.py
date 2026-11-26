#!/usr/bin/env python3
"""FRP Repair Studio — local guided dashboard (stdlib only).

Authorized device recovery / security research. Runs on 127.0.0.1 only.
"""

import json
import logging
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.tool_inventory import manifest_rows, tool_status
from app.usb_diagnostics import usb_report
from core.detector import DeviceDetector, identify_chipset
from core.method_selector import MethodSelector
from tools.wrappers import get_executor

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("repair-studio")

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
HOST, PORT = "127.0.0.1", 8484
CONFIRM_TOKEN = "ERASE"
SAFE_FUNCTIONS = {"printinfo", "printgpt", "read_partitions"}
LOGS_DIR = ROOT / "logs"

state: dict = {"session_id": time.strftime("%Y%m%d_%H%M%S"), "logs": []}

GUIDES: dict[str, list[str]] = {
    "adb": [
        "On the phone: Settings → About phone → tap Build number 7× to unlock Developer options.",
        "Settings → Developer options → enable USB debugging (and OEM unlocking if present).",
        "Plug in USB, accept the fingerprint prompt on the phone.",
        "If FRP-locked on setup wizard: USB-install / browser / file-manager paths are blocked on modern firmware — use a BROM/EDL/download-mode lane instead (see other lanes).",
    ],
    "fastboot": [
        "Power off the phone.",
        "Hold Volume Down + Power (most devices) until the fastboot screen appears; Xiaomi: Power + Volume Down, Samsung has no fastboot.",
        "Plug in USB. The device should appear in the table as fastboot.",
    ],
    "edl": [
        "Qualcomm EDL (9008) mode — brand key combo first:",
        "  Xiaomi: power off, hold Vol+ and Vol– together, plug USB.",
        "  OnePlus/Oppo: power off, hold Vol+ + Vol– (or dial *#*#727#*#* variants vary), plug USB.",
        "  Otherwise: testpoint on the motherboard (short the marked pads while plugging USB).",
        "Verify with lsusb: ID 05c6:9008 Qualcomm EDL.",
    ],
    "brom": [
        "MediaTek BootROM — power the phone fully off.",
        "Hold the BROM key combo while plugging USB: usually Vol Down (some: Vol Up, or both).",
        "If the phone boots instead: use a testpoint short on the board while plugging in, or battery-disconnect.",
        "BROM mode appears as 0e8d:0003 (or 0e8d:*0005 variants). Locked/authenticated loaders may refuse — do not force.",
    ],
    "download": [
        "Samsung Download (Odin) mode — power off.",
        "Hold Volume Down + Volume Up and plug in the USB cable, keep holding until the warning screen.",
        "Press Volume Up to continue into Download mode.",
        "Device shows as 04e8:685d / 04e8:9000 (Samsung).",
    ],
    "unknown": [
        "No device in any mode. Checklist:",
        "Cable: data-capable (charge-only cables are the #1 cause). Try another port, avoid hubs.",
        "adb/fastboot installed? (see Tools panel).",
        "udev rules: sudo usermap/udev rule for your device, or run with permissions for lsusb device nodes.",
        "Still nothing → try the mode-entry steps for your chipset (lanes above).",
    ],
}

LANE_HINTS = {
    "mediatek": "Best lane: mtkclient BROM erase (backup first).",
    "qualcomm": "Best lane: edl (9008) firehose erase, backup first.",
    "exynos": "Best lane: Samsung download mode / ADB modem tools; check baseband era.",
    "kirin": "Best lane: fastboot RAM hijack (Kirin 710) or testpoint + Sigma.",
    "unisoc": "Best lane: SPDClient / Termux or Download-mode erase.",
    "unknown": "Identify chipset first (adb shell getprop ro.board.platform).",
}


def detect_payload() -> dict:
    devices = DeviceDetector().detect_all()
    for dev in devices:
        dev.chipset = identify_chipset(dev)
    rows = []
    for dev in devices:
        d = asdict(dev)
        d["lane_hint"] = LANE_HINTS.get(dev.chipset, LANE_HINTS["unknown"])
        rows.append(d)
    return {"devices": rows}


def methods_payload(device: dict) -> dict:
    methods = MethodSelector().select_methods(device)
    rows = []
    for m in methods:
        rows.append({
            "tool": m.tool,
            "function": m.function,
            "priority": m.priority,
            "requires": m.requires,
            "compatibility": "unverified",
        })
    return {"methods": rows, "note": "compatibility is unverified until proven on this exact device + firmware"}


def execute_safely(payload: dict) -> dict:
    """Safety gate + dispatch. Never called directly by the HTTP layer."""
    tool = payload.get("tool", "")
    func = payload.get("function", "")
    device = payload.get("device", {})
    params = dict(payload.get("params", {}))
    dry_run = bool(payload.get("dry_run", True))

    base = {
        "tool": tool,
        "function": func,
        "params": params,
        "dry_run": dry_run,
        "timestamp": time.time(),
    }
    if not tool or not func:
        return {**base, "ok": False, "error": "tool and function are required"}

    if dry_run:
        return {**base, "ok": True, "executed": False,
                "message": f"DRY RUN — would call {tool}.{func}. Nothing was touched."}

    if func not in SAFE_FUNCTIONS and payload.get("confirm") != CONFIRM_TOKEN:
        return {**base, "ok": False, "executed": False,
                "error": f"{func} changes device state — type {CONFIRM_TOKEN} in the confirm box"}

    executor = get_executor(tool)
    if executor is None:
        return {**base, "ok": False, "executed": False,
                "error": f"{tool} is not installed — see Tools panel"}

    call = {"function": func, **params}
    logger.warning("EXECUTE %s.%s device=%s confirm=%s",
                   tool, func, device.get("serial", "?"), payload.get("confirm", ""))
    result = executor.execute(device, call)
    entry = {**base, "ok": True, "executed": True,
             "success": result.success,
             "output": (result.output or "")[-2000:],
             "error": (result.error or "")[-2000:],
             "duration_sec": result.duration_sec}
    state["logs"].append(entry)
    _append_log(entry)
    return entry


def _append_log(entry: dict) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    path = LOGS_DIR / f"session_{state['session_id']}.jsonl"
    with path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quiet
        logger.debug(fmt, *args)

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self) -> None:
        page = (STATIC / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._html()
        elif path == "/api/detect":
            self._json(detect_payload())
        elif path == "/api/usb-diagnostics":
            self._json(usb_report())
        elif path == "/api/tools":
            self._json({"tools": tool_status(), "manifest": manifest_rows()})
        elif path == "/api/logs":
            self._json({"logs": state["logs"]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"ok": False, "error": "bad json"}, 400)
            return
        if path == "/api/methods":
            self._json(methods_payload(payload.get("device", {})))
        elif path == "/api/execute":
            self._json(execute_safely(payload))
        else:
            self._json({"error": "not found"}, 404)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logger.warning("FRP Repair Studio → http://%s:%d  (Ctrl+C to stop)", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
