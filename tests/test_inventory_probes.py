"""Inventory must probe the actual tools, without executing phone commands."""
from app import tool_inventory as inventory


def test_fastboot_is_not_inferred_from_adb(monkeypatch):
    monkeypatch.setattr(inventory.shutil, "which", lambda name: "/usr/bin/adb" if name == "adb" else None)
    rows = {row["id"]: row for row in inventory.tool_status()}
    assert rows["adb"]["installed"] is True
    assert rows["fastboot"]["installed"] is False


def test_edl_checks_bkerler_module(monkeypatch):
    seen = []
    def find(name):
        seen.append(name)
    monkeypatch.setattr(inventory.importlib.util, "find_spec", find)
    inventory.tool_status()
    assert "edlclient" in seen
    assert "edl" not in seen


def test_install_hints_do_not_recommend_wrong_pypi_packages():
    hints = {row[0]: row[3] for row in inventory.CHECKS}
    assert "pip install edl " not in hints["edl"]
    assert "pip install mtkclient " not in hints["mtkclient"]
