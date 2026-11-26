"""Read-only host USB and ADB status; no device identifiers in the report."""

import re
import subprocess
from collections import Counter

_USB_ROW = re.compile(r"^Bus \d+ Device \d+: ID ([\da-f]{4}:[\da-f]{4})(?:\s|$)", re.I)
_ROOT_HUBS = {"1d6b:0001", "1d6b:0002", "1d6b:0003"}
_ADB_STATES = {"device": "authorized", "unauthorized": "unauthorized", "offline": "offline"}


def _probe(*argv: str) -> tuple[str, str]:
    try:
        # Only fixed local commands are passed by usb_report().
        result = subprocess.run(  # noqa: S603
            list(argv),
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
    except FileNotFoundError:
        return "missing", ""
    except subprocess.TimeoutExpired:
        return "timeout", ""
    except OSError:
        return "error", ""
    return ("ok", result.stdout) if result.returncode == 0 else ("error", "")


def adb_snapshot() -> tuple[str, list[list[str]]]:
    status, output = _probe("adb", "devices", "-l")
    rows = [
        line.split() for line in output.splitlines()
        if line.strip() and line.strip() != "List of devices attached"
        and not line.lstrip().startswith("*")
    ]
    return status, rows


def connection_snapshot() -> tuple[dict, list[list[str]]]:
    """Return aggregate USB/ADB results and private ADB rows for local logic only."""
    usb_status, usb_output = _probe("lsusb")
    adb_status, rows = adb_snapshot()
    usb_count = sum(
        match[1].lower() not in _ROOT_HUBS
        for line in usb_output.splitlines()
        if (match := _USB_ROW.match(line))
    )
    states: Counter[str] = Counter()
    for row in rows:
        if not row[1:]:
            continue
        if row[1:3] == ["no", "permissions"]:
            states["permission_denied"] += 1
        else:
            states[_ADB_STATES.get(row[1], "other")] += 1
    return {
        "usb": {
            "status": usb_status,
            "non_root_hub_count": usb_count if usb_status == "ok" else None,
        },
        "adb": {"status": adb_status, "states": dict(states)},
    }, rows


def usb_report() -> dict:
    report, _ = connection_snapshot()
    return report
