"""Tests for the Repair Studio app: safety gate, inventory, methods payload."""

import json
from pathlib import Path

import pytest

from app import server
from app.tool_inventory import manifest_rows, tool_status


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch, tmp_path):
    """Isolate module-level session state + log file writes per test."""
    monkeypatch.setattr(server, "state", {"session_id": "test", "logs": []})
    monkeypatch.setattr(server, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(server, "_append_log", lambda entry: None)


class TestSafetyGate:
    def test_dry_run_never_touches_an_executor(self, monkeypatch):
        monkeypatch.setattr(server, "get_executor",
                            lambda t: (_ for _ in ()).throw(AssertionError("touched")))
        out = server.execute_safely({
            "tool": "mtkclient", "function": "erase_partitions",
            "dry_run": True, "device": {},
        })
        assert out["ok"] is True
        assert out["executed"] is False
        assert "Nothing was touched" in out["message"]

    def test_destructive_requires_confirm_token(self, monkeypatch):
        monkeypatch.setattr(server, "get_executor",
                            lambda t: (_ for _ in ()).throw(AssertionError("touched")))
        out = server.execute_safely({
            "tool": "edl", "function": "erase_frp",
            "dry_run": False, "confirm": "yes please", "device": {},
        })
        assert out["ok"] is False
        assert out["executed"] is False
        assert "ERASE" in out["error"]

    def test_missing_tool_or_function_rejected(self):
        assert server.execute_safely({"dry_run": False, "confirm": "ERASE"})["ok"] is False

    def test_readonly_needs_no_confirm(self, monkeypatch):
        calls = {}

        class Fake:
            def execute(self, device, call):
                calls["call"] = call
                from tools.wrappers import ExecutionResult
                return ExecutionResult(True, "info ok", "", 0.1)

        monkeypatch.setattr(server, "get_executor", lambda t: Fake())
        out = server.execute_safely({
            "tool": "mtkclient", "function": "printinfo",
            "dry_run": False, "device": {},
        })
        assert out["ok"] is True and out["executed"] is True
        assert calls["call"]["function"] == "printinfo"


class TestInventory:
    def test_tool_status_rows_complete(self):
        rows = tool_status()
        assert rows, "inventory empty"
        for r in rows:
            assert r["state"] in {"installed", "source", "missing"}
            assert isinstance(r["installed"], bool)
            assert r["id"] and r["label"] and r["install_hint"]

    def test_manifest_rows_read(self):
        rows = manifest_rows()
        assert isinstance(rows, list)
        for r in rows:
            assert "folder" in r and "status" in r


class TestMethodsPayload:
    def test_no_success_rate_leaks_and_compatibility_unverified(self):
        out = server.methods_payload({
            "chipset": "mediatek", "brand": "xiaomi",
            "connection_type": "brom",
        })
        text = json.dumps(out)
        assert "success_rate" not in text and "successRate" not in text
        assert all(m["compatibility"] == "unverified" for m in out["methods"])
        assert out["note"]

    def test_unknown_chipset_falls_back(self):
        out = server.methods_payload({"chipset": "mt6789", "connection_type": "brom"})
        assert out["methods"]


class TestGuide:
    def test_every_lane_has_steps(self):
        for lane in ["adb", "fastboot", "edl", "brom", "download", "unknown"]:
            assert server.GUIDES[lane], f"empty guide for {lane}"

    def test_detect_payload_shape(self):
        out = server.detect_payload()
        assert isinstance(out["devices"], list)


class TestLogs:
    def test_not_installed_is_refused_and_not_logged(self, monkeypatch):
        monkeypatch.setattr(server, "get_executor", lambda t: None)
        out = server.execute_safely({
            "tool": "mtkclient", "function": "erase_partitions",
            "dry_run": False, "confirm": "ERASE", "device": {},
        })
        assert out["ok"] is False and "not installed" in out["error"]
        assert server.state["logs"] == []

    def test_successful_execution_is_logged(self, monkeypatch):
        from tools.wrappers import ExecutionResult

        class Fake:
            def execute(self, device, call):
                return ExecutionResult(True, "did it", "", 0.2)

        monkeypatch.setattr(server, "get_executor", lambda t: Fake())
        out = server.execute_safely({
            "tool": "mtkclient", "function": "printinfo",
            "dry_run": False, "device": {},
        })
        assert out["ok"] is True and out["executed"] is True
        assert len(server.state["logs"]) == 1
        entry = server.state["logs"][0]
        assert entry["tool"] == "mtkclient" and entry["function"] == "printinfo"


def test_static_dashboard_exists():
    assert (Path(server.STATIC) / "index.html").is_file()
