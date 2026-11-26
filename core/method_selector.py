#!/usr/bin/env python3
"""
FRP Bot — Method Selection Engine
Maps (brand, model, chipset, android_version, security_patch, connection_type) → best bypass method
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BypassMethod:
    tool: str                    # mtkclient, edl, nphonekit, frp_freedom, kirin_toolkit, spd_client
    function: str                # function/command to call
    params: dict[str, Any]       # parameters for the function
    priority: int                # lower = higher priority
    conditions: dict[str, Any]   # when this method applies
    success_rate: float = 0.0    # estimated from community data
    requires: list[str] = None   # prerequisites: testpoint, root, unlocked_bl, etc.

    def __post_init__(self):
        if self.requires is None:
            self.requires = []


class MethodSelector:
    """
    Selects optimal bypass method based on device fingerprint.
    Priority logic: official recovery → software exploit → testpoint → hardware (JTAG/ISP)
    """

    def __init__(self):
        self.methods_db = self._build_methods_db()

    def _build_methods_db(self) -> dict[str, list[BypassMethod]]:
        """Build the method database organized by chipset family"""
        return {
            "mediatek": [
                # Primary: mtkclient FRP erase (works on most MTK devices in BROM)
                BypassMethod(
                    tool="mtkclient",
                    function="erase_partitions",
                    params={"partitions": ["frp", "persist"]},
                    priority=10,
                    conditions={"connection_type": "brom"},
                    success_rate=0.85,
                    requires=["brom_mode", "mtk_drivers"],
                ),
                # V6 preloader: mtkclient with --loader for patched-BROM Dimensity
                BypassMethod(
                    tool="mtkclient",
                    function="erase_partitions_da",
                    params={"partitions": ["frp", "persist"], "loader": "auto"},
                    priority=15,
                    conditions={"connection_type": "preloader", "chipset_gen": "v6"},
                    success_rate=0.70,
                    requires=["preloader_mode", "mtk_drivers", "da_loader"],
                ),
                # Carbonara: DA2 hash-slot overwrite (patched Sept 2025, but works on older DA builds)
                BypassMethod(
                    tool="penumbra",
                    function="carbonara_da2_bypass",
                    params={"payload": "a4de2200000000002000000000000000"},
                    priority=20,
                    conditions={"connection_type": "preloader", "chipset_gen": "v5"},
                    success_rate=0.60,
                    requires=["preloader_mode", "signed_da1", "penumbra_installed"],
                ),
                # heapb8: DA2 AIO heap overflow (patched Nov 2024)
                BypassMethod(
                    tool="penumbra",
                    function="heapb8_da2_overflow",
                    params={},
                    priority=25,
                    conditions={"connection_type": "preloader", "chipset_gen": "v6", "da_date": "<2024-11"},
                    success_rate=0.55,
                    requires=["preloader_mode", "vulnerable_da2", "penumbra_installed"],
                ),
                # GUI wrapper for less technical users
                BypassMethod(
                    tool="mtk_studio",
                    function="gui_bypass",
                    params={},
                    priority=30,
                    conditions={"connection_type": "brom"},
                    success_rate=0.80,
                    requires=["brom_mode", "mtk_drivers", "gui"],
                ),
                # frp-freedom MTK path
                BypassMethod(
                    tool="frp_freedom",
                    function="mtk_bypass_exploit",
                    params={},
                    priority=40,
                    conditions={"connection_type": ["adb", "brom"]},
                    success_rate=0.60,
                    requires=["adb_or_brom"],
                ),
                # Valhalla: Motorola MTK BL unlock + FRP (Val Protocol exploit)
                BypassMethod(
                    tool="valhalla",
                    function="val_protocol_unlock",
                    params={},
                    priority=15,
                    conditions={"brand": "motorola", "connection_type": "fastboot"},
                    success_rate=0.70,
                    requires=["fastboot", "stock_lk_img"],
                ),
            ],

            "qualcomm": [
                # Primary: EDL mode FRP erase
                BypassMethod(
                    tool="edl",
                    function="erase_frp",
                    params={"partitions": ["frp", "persist", "modemst1", "modemst2"]},
                    priority=10,
                    conditions={"connection_type": "edl"},
                    success_rate=0.80,
                    requires=["edl_mode", "edl_drivers", "firehose_loader"],
                ),
                # EDL with custom firehose for specific device
                BypassMethod(
                    tool="edl",
                    function="erase_frp_custom_loader",
                    params={"loader": "device_specific"},
                    priority=15,
                    conditions={"connection_type": "edl", "has_custom_loader": True},
                    success_rate=0.90,
                    requires=["edl_mode", "custom_firehose"],
                ),
                # Zygote CVE-2024-31317: no-root Zygote injection (ADB → system_uid shell)
                BypassMethod(
                    tool="zygote_cve_2024_31317",
                    function="inject_and_extract",
                    params={"target_pkg": "com.android.settings", "mode": "interactive"},
                    priority=18,
                    conditions={
                        "connection_type": "adb",
                        "android_version": ["9", "10", "11", "12", "13", "14"],
                        "security_patch": "<=2024-06-01"
                    },
                    success_rate=0.75,
                    requires=["adb", "android_sdk_build_tools", "jdk17"],
                ),
                # Enable ADB via diag then use ADB exploits
                BypassMethod(
                    tool="edl",
                    function="enable_adb_then_frp",
                    params={},
                    priority=25,
                    conditions={"connection_type": "edl", "supports_diag": True},
                    success_rate=0.50,
                    requires=["edl_mode", "diag_support"],
                ),
                # frp-freedom Qualcomm EDL path
                BypassMethod(
                    tool="frp_freedom",
                    function="qualcomm_edl_exploit",
                    params={},
                    priority=30,
                    conditions={"connection_type": ["adb", "edl"]},
                    success_rate=0.55,
                    requires=["adb_or_edl"],
                ),
            ],

            "exynos": [
                # Samsung USA 2024 devices (nPhoneKIT)
                BypassMethod(
                    tool="nphonekit",
                    function="frp_unlock_2024",
                    params={},
                    priority=10,
                    conditions={
                        "brand": "samsung",
                        "region": "usa",
                        "security_patch": ">=2024-01-01"
                    },
                    success_rate=0.75,
                    requires=["adb", "modem_mode"],
                ),
                # Samsung Aug 2022 - Dec 2022
                BypassMethod(
                    tool="nphonekit",
                    function="frp_unlock_2022_2023",
                    params={},
                    priority=15,
                    conditions={
                        "brand": "samsung",
                        "security_patch": ">=2022-08-01,<2023-01-01"
                    },
                    success_rate=0.85,
                    requires=["adb", "modem_mode"],
                ),
                # Samsung Pre-Aug 2022
                BypassMethod(
                    tool="nphonekit",
                    function="frp_unlock_pre2022",
                    params={},
                    priority=20,
                    conditions={
                        "brand": "samsung",
                        "security_patch": "<2022-08-01"
                    },
                    success_rate=0.95,
                    requires=["adb", "modem_mode"],
                ),
                # Download mode + frp-freedom Odin exploit
                BypassMethod(
                    tool="frp_freedom",
                    function="odin_mode_exploit",
                    params={},
                    priority=30,
                    conditions={"brand": "samsung", "connection_type": "download"},
                    success_rate=0.70,
                    requires=["download_mode", "odin"],
                ),
                # Samsung download-mode server FRP reset (paid, all SPLs, Android 12-16)
                BypassMethod(
                    tool="samfw_server",
                    function="download_mode_frp_reset",
                    params={},
                    priority=22,
                    conditions={
                        "brand": "samsung",
                        "connection_type": "download",
                        "android_version": ["12", "13", "14", "15", "16"]
                    },
                    success_rate=0.90,
                    requires=["download_mode", "samfw_credits", "windows_pc"],
                ),
                # WebSerial/WebUSB method (pre-Aug 2022 only)
                BypassMethod(
                    tool="samsung_frp_web",
                    function="webserial_bypass",
                    params={},
                    priority=40,
                    conditions={
                        "brand": "samsung",
                        "security_patch": "<2022-08-01",
                        "has_test_mode": True
                    },
                    success_rate=0.80,
                    requires=["test_mode", "chromium_browser", "samsung_drivers"],
                ),
                # F.U_frp modem mode automation
                BypassMethod(
                    tool="fu_frp",
                    function="modem_mode_bypass",
                    params={},
                    priority=50,
                    conditions={"brand": "samsung", "connection_type": ["adb", "download"]},
                    success_rate=0.65,
                    requires=["adb_or_download"],
                ),
            ],

            "kirin": [
                # Kirin 710/710F no-testpoint fastboot RAM hijack
                BypassMethod(
                    tool="kirin_toolkit",
                    function="fastboot_ram_hijack",
                    params={
                        "addresses": ["0x3C3E4ED8", "0x3C3EC1F0", "0x3C412344"],
                        "values": ["0x3C001364", "0x3C001364", "0x00000001"]
                    },
                    priority=10,
                    conditions={
                        "chipset": ["kirin710", "kirin710f", "hi6260"],
                        "connection_type": "fastboot"
                    },
                    success_rate=0.90,
                    requires=["fastboot", "unlocked_bootloader"],
                ),
                # Kirin 650/655/658/659/960/970 testpoint + Sigma
                BypassMethod(
                    tool="sigma",
                    function="testpoint_frp_erase",
                    params={},
                    priority=20,
                    conditions={
                        "chipset": ["kirin650", "kirin655", "kirin658", "kirin659", "kirin960", "kirin970"],
                        "has_testpoint": True
                    },
                    success_rate=0.95,
                    requires=["testpoint", "sigma_dongle", "com_port"],
                ),
                # Board software flasher (SigmaKey dumps)
                BypassMethod(
                    tool="kirin_toolkit",
                    function="flash_board_software",
                    params={"dump_format": "skd"},
                    priority=30,
                    conditions={"has_sigma_dump": True},
                    success_rate=0.85,
                    requires=["fastboot", "sigma_dump"],
                ),
            ],

            "unisoc": [
                # SPDClient Termux (no PC needed)
                BypassMethod(
                    tool="spd_client",
                    function="erase_frp_partition",
                    params={"partition": "frp"},
                    priority=10,
                    conditions={"platform": "termux"},
                    success_rate=0.75,
                    requires=["termux", "otg_cable", "download_mode"],
                ),
                # spd-flasher-apk (Android app)
                BypassMethod(
                    tool="spd_flasher_apk",
                    function="erase_frp",
                    params={},
                    priority=15,
                    conditions={"platform": "android"},
                    success_rate=0.70,
                    requires=["root_or_nonroot", "download_mode"],
                ),
                # unisoc_tools BROM exploit (T606/UMS9230)
                BypassMethod(
                    tool="unisoc_tools",
                    function="brom_exploit_frp",
                    params={},
                    priority=20,
                    conditions={"chipset": "ums9230"},
                    success_rate=0.80,
                    requires=["brom_mode", "linux_pc"],
                ),
                # CVE-2022-38694 persist/FRP erase
                BypassMethod(
                    tool="cve_2022_38694",
                    function="erase_persist_frp",
                    params={},
                    priority=25,
                    conditions={"vulnerable_bootrom": True},
                    success_rate=0.85,
                    requires=["edl_mode", "spd_dump", "device_package"],
                ),
                # PC-based SPD Research Tool
                BypassMethod(
                    tool="spd_research_tool",
                    function="frp_reset",
                    params={},
                    priority=35,
                    conditions={"platform": "windows"},
                    success_rate=0.70,
                    requires=["windows", "spd_drivers", "download_mode"],
                ),
            ],

            "unknown": [
                # Generic frp-freedom fallback
                BypassMethod(
                    tool="frp_freedom",
                    function="auto_detect_bypass",
                    params={},
                    priority=10,
                    conditions={},
                    success_rate=0.40,
                    requires=["adb"],
                ),
            ],

            "hardware": [
                # eMMC ISP: direct partition erase via soldered ISP pads
                BypassMethod(
                    tool="easyjtag_plus",
                    function="isp_erase_frp",
                    params={"partitions": ["frp", "persistent", "misc"]},
                    priority=10,
                    conditions={"storage_type": "emmc"},
                    success_rate=0.90,
                    requires=["isp_pads", "easyjtag_box", "soldering", "microscope"],
                ),
                # UFS ISP: direct partition erase for 2024+ flagships
                BypassMethod(
                    tool="easyjtag_plus",
                    function="ufs_isp_erase_frp",
                    params={"partitions": ["frp", "persistent", "misc"]},
                    priority=15,
                    conditions={"storage_type": "ufs"},
                    success_rate=0.85,
                    requires=["ufs_isp_adapter", "easyjtag_lx9", "soldering", "microscope", "bench_psu"],
                ),
                # Medusa Pro II UFS ISP (alternative box)
                BypassMethod(
                    tool="medusa_pro_2",
                    function="ufs_isp_erase_frp",
                    params={"partitions": ["frp", "persistent", "misc"]},
                    priority=16,
                    conditions={"storage_type": "ufs"},
                    success_rate=0.85,
                    requires=["ufs_isp_adapter", "medusa_box", "soldering", "microscope"],
                ),
                # UFS socket: chip removed, programmed in socket
                BypassMethod(
                    tool="easyjtag_plus",
                    function="ufs_socket_erase_frp",
                    params={"partitions": ["frp", "persistent", "misc"]},
                    priority=25,
                    conditions={"storage_type": "ufs", "chip_removed": True},
                    success_rate=0.90,
                    requires=["ufs_socket", "easyjtag_box", "bga_rework_station", "reballing_stencil"],
                ),
            ],
        }

    def select_methods(self, device_info: dict[str, Any]) -> list[BypassMethod]:
        """
        Select and rank applicable methods for a device.
        Returns list sorted by priority (ascending).
        """
        chipset = device_info.get("chipset", "unknown").lower()
        brand = device_info.get("brand", "").lower()
        model = device_info.get("model", "").lower()
        android_ver = device_info.get("android_version", "")
        sec_patch = device_info.get("security_patch", "")
        conn_type = device_info.get("connection_type", "unknown")

        # Normalize chipset family
        chipset_family = self._normalize_chipset(chipset, brand, model, device_info)

        # Get candidate methods
        candidates = self.methods_db.get(chipset_family, self.methods_db["unknown"])

        # Filter by conditions
        applicable = []
        for method in candidates:
            if self._match_conditions(method.conditions, {
                "chipset": chipset,
                "chipset_family": chipset_family,
                "brand": brand,
                "model": model,
                "android_version": android_ver,
                "security_patch": sec_patch,
                "connection_type": conn_type,
                **device_info
            }):
                applicable.append(method)

        # Sort by priority
        applicable.sort(key=lambda m: m.priority)

        logger.info(f"Device: {brand} {model} ({chipset_family}) → {len(applicable)} applicable methods")
        for m in applicable:
            logger.info(f"  [{m.priority}] {m.tool}.{m.function} (success~{m.success_rate:.0%}) requires: {m.requires}")

        return applicable

    def _normalize_chipset(self, chipset: str, brand: str, model: str, device_info: dict = None) -> str:
        """Map raw chipset string to family"""
        chipset = chipset.lower()

        # Hardware methods take priority when connection_type or storage_type indicates ISP/socket
        device_info = device_info or {}
        conn = str(device_info.get("connection_type", "")).lower()
        storage = str(device_info.get("storage_type", "")).lower()
        if any(x in chipset for x in ["isp", "ufs_isp", "emmc_isp", "socket", "chipoff"]) or \
           any(x in conn for x in ["isp", "socket", "chipoff"]) or \
           any(x in storage for x in ["isp"]):
            return "hardware"

        if any(x in chipset for x in ["mt", "helio", "dimensity", "mtk", "mt67", "mt68", "mt81", "mt87"]):
            return "mediatek"
        if any(x in chipset for x in ["snapdragon", "msm", "sdm", "sm", "qcom", "qualcomm", "apq"]):
            # Samsung with Snapdragon in download mode → still Samsung methods apply
            if brand == "samsung":
                return "exynos"  # exynos family handles both Samsung SoC types
            return "qualcomm"
        if any(x in chipset for x in ["exynos", "s5e", "s5p", "universal"]):
            return "exynos"
        if any(x in chipset for x in ["kirin", "hi36", "hi62"]):
            return "kirin"
        if any(x in chipset for x in ["unisoc", "spreadtrum", "ums", "sc98", "t606", "t610", "t612", "t616", "t618", "t700", "t760", "t820"]):
            return "unisoc"

        # Brand-based fallback
        if brand in ["huawei", "honor"]:
            return "kirin"
        if brand == "samsung":
            return "exynos"  # Could be snapdragon too — need connection_type
        if brand in ["tecno", "infinix", "itel"]:
            return "mediatek|unisoc"

        return "unknown"

    def _match_conditions(self, conditions: dict[str, Any], device: dict[str, Any]) -> bool:
        """Check if device matches method conditions"""
        for key, expected in conditions.items():
            actual = device.get(key)

            if actual is None:
                return False

            # Handle list of acceptable values
            if isinstance(expected, list):
                if actual not in expected:
                    return False
                continue

            # Handle comparison operators for security_patch
            if key == "security_patch" and isinstance(expected, str):
                if not self._compare_security_patch(actual, expected):
                    return False
                continue

            # Handle chipset_gen: check device's chipset_gen field, not chipset string
            if key == "chipset_gen" and isinstance(expected, str):
                actual_gen = device.get("chipset_gen", "")
                if expected not in str(actual_gen):
                    return False
                continue

            # Exact match
            if actual != expected:
                return False

        return True

    def _compare_security_patch(self, actual: str, expected: str) -> bool:
        """Compare security patch strings with operators: >=, <=, <, >, =="""
        try:
            # Parse actual patch date
            actual_date = actual.strip()
            if not actual_date or actual_date == "0000-00-00":
                return False

            # Parse expected condition
            if expected.startswith(">="):
                target = expected[2:]
                return actual_date >= target
            if expected.startswith("<="):
                target = expected[2:]
                return actual_date <= target
            if expected.startswith(">"):
                target = expected[1:]
                return actual_date > target
            if expected.startswith("<"):
                target = expected[1:]
                return actual_date < target
            if expected.startswith("=="):
                target = expected[2:]
                return actual_date == target
            return actual_date == expected
        except Exception:
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    selector = MethodSelector()

    # Test cases
    test_devices = [
        {
            "brand": "samsung",
            "model": "SM-G991U",
            "chipset": "exynos2100",
            "android_version": "14",
            "security_patch": "2024-05-01",
            "connection_type": "adb",
        },
        {
            "brand": "xiaomi",
            "model": "Redmi Note 11",
            "chipset": "mt6789",
            "android_version": "13",
            "security_patch": "2023-08-01",
            "connection_type": "brom",
        },
        {
            "brand": "huawei",
            "model": "P30 Lite",
            "chipset": "kirin710",
            "android_version": "10",
            "security_patch": "2020-12-01",
            "connection_type": "fastboot",
        },
        {
            "brand": "tecno",
            "model": "Pop 2F",
            "chipset": "mt6761",
            "android_version": "9",
            "security_patch": "2019-12-01",
            "connection_type": "brom",
        },
    ]

    for dev in test_devices:
        print(f"\n{'='*60}")
        print(f"Testing: {dev['brand']} {dev['model']}")
        methods = selector.select_methods(dev)
        for m in methods[:3]:
            print(f"  → {m.tool}.{m.function} (prio={m.priority}, rate={m.success_rate:.0%})")
