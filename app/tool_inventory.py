#!/usr/bin/env python3
"""FRP Repair Studio — tool inventory: what is installed vs only downloaded."""

import importlib.util
import json
import shutil
from pathlib import Path

FRP_TOOLS_DIR = Path.home() / "frp-tools"
MANIFEST = FRP_TOOLS_DIR / "download-manifest.json"

# id, label, kind, hint  — kind: binary | module:<name> | dir:<folder>
CHECKS = [
    ("adb", "Android platform-tools — adb", "binary:adb",
     "sudo apt install adb (or google platform-tools)"),
    ("fastboot", "Android platform-tools — fastboot", "binary:fastboot",
     "sudo apt install fastboot (or google platform-tools)"),
    ("mtkclient", "mtkclient — MediaTek BROM/Preloader", "module:mtkclient",
     "Install official bkerler source: ~/frp-tools/MediaTek-Flash-and-Repair-mtkclient-upstream"),
    ("edl", "edl — Qualcomm EDL / firehose", "module:edlclient",
     "Install official bkerler source: ~/frp-tools/Qualcomm-EDL-and-Diagnostics-edl-upstream (not PyPI edl)"),
    ("nphonecli", "nPhoneCLI — Samsung ADB/modem FRP", "module:nphonecli",
     "pip install git+https://github.com/nlckysolutions/nPhoneCLI"),
    ("frp_freedom", "frp-freedom — multi-OEM FRP", "module:frp_freedom",
     "pip install git+https://github.com/youngrichu/frp-freedom"),
    ("spdclient", "SpdClient — Unisoc BootROM (source only)", "dir:Unisoc-Spreadtrum-BootROM-SpdClient",
     "Source in ~/frp-tools — Python runner not installed; runtime untested"),
]


def _probe(kind: str) -> tuple[str, str]:
    """Returns (state, detail) — state: installed | source | missing."""
    if kind.startswith("binary:"):
        path = shutil.which(kind.split(":", 1)[1])
        return ("installed" if path else "missing", path or "")
    if kind.startswith("module:"):
        name = kind.split(":", 1)[1]
        spec = importlib.util.find_spec(name)
        state = "installed" if spec else "missing"
        return (state, getattr(spec, "origin", "") or "")
    if kind.startswith("dir:"):
        folder = FRP_TOOLS_DIR / kind.split(":", 1)[1]
        return ("source" if folder.is_dir() else "missing", str(folder))
    return ("missing", "")


def tool_status() -> list[dict]:
    rows = []
    for tool_id, label, kind, hint in CHECKS:
        state, where = _probe(kind)
        rows.append({
            "id": tool_id,
            "label": label,
            "state": state,
            "installed": state == "installed",
            "detail": where,
            "install_hint": hint,
        })
    return rows


def manifest_rows() -> list[dict]:
    if not MANIFEST.is_file():
        return []
    try:
        data = json.loads(MANIFEST.read_text())
    except json.JSONDecodeError:
        return []
    out = []
    for row in data:
        out.append({
            "folder": row.get("folder", row.get("requested", "?")),
            "status": row.get("status", "unknown"),
            "url": row.get("url", ""),
            "requested": row.get("requested", ""),
        })
    return out
