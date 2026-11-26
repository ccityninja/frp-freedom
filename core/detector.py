#!/usr/bin/env python3
"""
FRP Bot — Core Device Detection & Chipset Identification
"""

import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    """Unified device representation across ADB, Fastboot, EDL, BROM"""
    serial: str = ""
    brand: str = ""
    model: str = ""
    chipset: str = ""
    android_version: str = ""
    security_patch: str = ""
    connection_type: str = "unknown"  # adb, fastboot, edl, brom, download
    usb_vid: str = ""
    usb_pid: str = ""
    properties: dict[str, str] = field(default_factory=dict)
    partitions: list[str] = field(default_factory=list)


class DeviceDetector:
    """Multi-protocol device detection: ADB → Fastboot → EDL → BROM → Download"""

    def __init__(self):
        self.adb_path = self._find_binary("adb")
        self.fastboot_path = self._find_binary("fastboot")
        self.mtk_path = self._find_mtkclient()
        self.edl_path = self._find_binary("edl")

    def _find_binary(self, name: str) -> str | None:
        try:
            result = subprocess.run(["which", name], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _find_mtkclient(self) -> str | None:
        # Check common install locations
        candidates = [
            "mtk",
            "python -m mtkclient",
            str(Path.home() / "mtkclient" / "mtk.py"),
            "/usr/local/bin/mtk",
        ]
        for c in candidates:
            try:
                result = subprocess.run(c.split() + ["--help"], capture_output=True, timeout=5)
                if result.returncode == 0:
                    return c
            except Exception:
                continue
        return None

    def detect_all(self) -> list[DeviceInfo]:
        """Run all detection methods and merge results"""
        devices = []

        # 1. ADB devices (highest-level, most info)
        devices.extend(self._detect_adb())

        # 2. Fastboot devices
        devices.extend(self._detect_fastboot())

        # 3. EDL devices (Qualcomm)
        devices.extend(self._detect_edl())

        # 4. BROM/Preloader devices (MediaTek)
        devices.extend(self._detect_brom())

        # 5. Download mode (Samsung/Odin)
        devices.extend(self._detect_download_mode())

        # Merge by serial/USB ID
        return self._merge_devices(devices)

    def _detect_adb(self) -> list[DeviceInfo]:
        if not self.adb_path:
            return []
        devices = []
        try:
            result = subprocess.run(
                [self.adb_path, "devices", "-l"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split("\n")[1:]:
                if not line.strip() or "device" not in line:
                    continue
                parts = line.split()
                serial = parts[0]
                # Get detailed props
                props = self._get_adb_props(serial)
                devices.append(DeviceInfo(
                    serial=serial,
                    brand=props.get("ro.product.brand", "").lower(),
                    model=props.get("ro.product.model", ""),
                    chipset=props.get("ro.hardware.chipname", props.get("ro.board.platform", "")),
                    android_version=props.get("ro.build.version.release", ""),
                    security_patch=props.get("ro.build.version.security_patch", ""),
                    connection_type="adb",
                    properties=props,
                ))
        except Exception as e:
            logger.debug(f"ADB detection failed: {e}")
        return devices

    def _get_adb_props(self, serial: str) -> dict[str, str]:
        props = {}
        try:
            result = subprocess.run(
                [self.adb_path, "-s", serial, "shell", "getprop"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split("\n"):
                match = re.match(r"\[(.*?)\]:\s*\[(.*?)\]", line)
                if match:
                    props[match.group(1)] = match.group(2)
        except Exception:
            pass
        return props

    def _detect_fastboot(self) -> list[DeviceInfo]:
        if not self.fastboot_path:
            return []
        devices = []
        try:
            result = subprocess.run(
                [self.fastboot_path, "devices"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split("\n"):
                if not line.strip() or "fastboot" not in line:
                    continue
                serial = line.split()[0]
                # Get fastboot variables
                vars_out = self._get_fastboot_vars(serial)
                devices.append(DeviceInfo(
                    serial=serial,
                    brand=vars_out.get("product", "").lower(),
                    model=vars_out.get("product", ""),
                    chipset=vars_out.get("chipname", vars_out.get("platform", "")),
                    connection_type="fastboot",
                    properties=vars_out,
                ))
        except Exception as e:
            logger.debug(f"Fastboot detection failed: {e}")
        return devices

    def _get_fastboot_vars(self, serial: str) -> dict[str, str]:
        vars_dict = {}
        keys = ["product", "chipname", "platform", "version", "secure", "unlocked"]
        for key in keys:
            try:
                result = subprocess.run(
                    [self.fastboot_path, "-s", serial, "getvar", key],
                    capture_output=True, text=True, timeout=5
                )
                # fastboot outputs to stderr
                match = re.search(rf"{key}:\s*(.+)", result.stderr)
                if match:
                    vars_dict[key] = match.group(1).strip()
            except Exception:
                pass
        return vars_dict

    def _detect_edl(self) -> list[DeviceInfo]:
        if not self.edl_path:
            return []
        devices = []
        try:
            # edl printgpt detects EDL devices
            result = subprocess.run(
                [self.edl_path, "printgpt"],
                capture_output=True, text=True, timeout=15
            )
            if "GPT" in result.stdout or "partition" in result.stdout.lower():
                # Parse USB info from lsusb or edl output
                vid, pid = self._get_edl_usb_ids()
                devices.append(DeviceInfo(
                    serial=f"edl_{vid}_{pid}",
                    chipset="qualcomm",
                    connection_type="edl",
                    usb_vid=vid,
                    usb_pid=pid,
                ))
        except Exception as e:
            logger.debug(f"EDL detection failed: {e}")
        return devices

    def _get_edl_usb_ids(self) -> tuple[str, str]:
        try:
            result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
            for line in result.stdout.split("\n"):
                if "Qualcomm" in line or "05c6" in line or "9008" in line:
                    match = re.search(r"ID\s+([0-9a-f]{4}):([0-9a-f]{4})", line)
                    if match:
                        return match.group(1), match.group(2)
        except Exception:
            pass
        return "05c6", "9008"  # Default Qualcomm EDL

    def _detect_brom(self) -> list[DeviceInfo]:
        if not self.mtk_path:
            return []
        devices = []
        try:
            # mtkclient printinfo in BROM mode
            result = subprocess.run(
                self.mtk_path.split() + ["printinfo"],
                capture_output=True, text=True, timeout=20
            )
            if "BROM" in result.stdout or "PRELOADER" in result.stdout:
                vid, pid = self._get_mtk_usb_ids()
                devices.append(DeviceInfo(
                    serial=f"mtk_{vid}_{pid}",
                    chipset="mediatek",
                    connection_type="brom",
                    usb_vid=vid,
                    usb_pid=pid,
                ))
        except Exception as e:
            logger.debug(f"BROM detection failed: {e}")
        return devices

    def _get_mtk_usb_ids(self) -> tuple[str, str]:
        try:
            result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
            for line in result.stdout.split("\n"):
                if "MediaTek" in line or "0e8d" in line:
                    match = re.search(r"ID\s+([0-9a-f]{4}):([0-9a-f]{4})", line)
                    if match:
                        return match.group(1), match.group(2)
        except Exception:
            pass
        return "0e8d", "0003"  # Default MTK BROM

    def _detect_download_mode(self) -> list[DeviceInfo]:
        """Samsung Download/Odin mode detection via lsusb"""
        devices = []
        try:
            result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
            for line in result.stdout.split("\n"):
                if "Samsung" in line and ("04e8" in line or "685d" in line or "6860" in line):
                    match = re.search(r"ID\s+([0-9a-f]{4}):([0-9a-f]{4})", line)
                    if match:
                        vid, pid = match.group(1), match.group(2)
                        devices.append(DeviceInfo(
                            serial=f"sam_dl_{vid}_{pid}",
                            brand="samsung",
                            chipset="exynos|snapdragon",
                            connection_type="download",
                            usb_vid=vid,
                            usb_pid=pid,
                        ))
        except Exception as e:
            logger.debug(f"Download mode detection failed: {e}")
        return devices

    def _merge_devices(self, devices: list[DeviceInfo]) -> list[DeviceInfo]:
        """Merge detections by USB VID/PID or serial"""
        merged = {}
        for dev in devices:
            key = dev.serial
            if dev.usb_vid and dev.usb_pid:
                key = f"{dev.usb_vid}:{dev.usb_pid}"
            if key in merged:
                # Prefer ADB > Fastboot > EDL > BROM > Download for info richness
                priority = {"adb": 5, "fastboot": 4, "edl": 3, "brom": 2, "download": 1}
                if priority.get(dev.connection_type, 0) > priority.get(merged[key].connection_type, 0):
                    merged[key] = dev
            else:
                merged[key] = dev
        return list(merged.values())


def identify_chipset(device: DeviceInfo) -> str:
    """
    Normalize chipset identification from various sources.
    Returns canonical chipset family: mediatek, qualcomm, exynos, kirin, unisoc, unknown
    """
    chipset = (device.chipset or "").lower()
    brand = (device.brand or "").lower()
    model = (device.model or "").lower()
    hw = device.properties.get("ro.hardware", "").lower()
    board = device.properties.get("ro.board.platform", "").lower()
    cpuinfo = device.properties.get("ro.hardware.chipname", "").lower()

    # MediaTek patterns
    mtk_patterns = ["mt", "helio", "dimensity", "mtk", "mt67", "mt68", "mt81", "mt87"]
    if any(p in chipset for p in mtk_patterns) or any(p in hw for p in mtk_patterns) or any(p in board for p in mtk_patterns):
        return "mediatek"

    # Qualcomm patterns
    qc_patterns = ["snapdragon", "msm", "sdm", "sm", "qcom", "qualcomm", "apq"]
    if any(p in chipset for p in qc_patterns) or any(p in hw for p in qc_patterns) or any(p in board for p in qc_patterns):
        return "qualcomm"

    # Samsung Exynos
    exynos_patterns = ["exynos", "s5e", "s5p", "universal"]
    if any(p in chipset for p in exynos_patterns) or any(p in hw for p in exynos_patterns) or any(p in board for p in exynos_patterns):
        return "exynos"

    # Huawei/Honor Kirin
    kirin_patterns = ["kirin", "hi36", "hi62", "kirin"]
    if any(p in chipset for p in kirin_patterns) or any(p in cpuinfo for p in kirin_patterns) or "huawei" in brand or "honor" in brand:
        if any(p in chipset for p in kirin_patterns) or any(p in cpuinfo for p in kirin_patterns):
            return "kirin"

    # Unisoc/Spreadtrum
    unisoc_patterns = ["unisoc", "spreadtrum", "ums", "sc98", "t606", "t610", "t612", "t616", "t618", "t700", "t760", "t820"]
    if any(p in chipset for p in unisoc_patterns) or any(p in hw for p in unisoc_patterns) or any(p in board for p in unisoc_patterns):
        return "unisoc"

    # Fallback by brand
    if brand in ["xiaomi", "redmi", "poco", "oppo", "realme", "vivo", "iqoo", "oneplus", "motorola", "tecno", "infinix", "itel"]:
        # These brands use mixed chipsets — need hardware detection
        pass

    if device.connection_type == "edl":
        return "qualcomm"
    if device.connection_type == "brom":
        return "mediatek"
    if device.connection_type == "download":
        return "exynos|snapdragon"

    return "unknown"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    detector = DeviceDetector()
    devices = detector.detect_all()

    if not devices:
        print("No devices detected. Check USB connection, drivers, and device mode.")
        sys.exit(1)

    for dev in devices:
        chipset = identify_chipset(dev)
        print(f"\n{'='*60}")
        print(f"Serial:       {dev.serial}")
        print(f"Brand:        {dev.brand}")
        print(f"Model:        {dev.model}")
        print(f"Chipset:      {chipset} (raw: {dev.chipset})")
        print(f"Android:      {dev.android_version}")
        print(f"Sec Patch:    {dev.security_patch}")
        print(f"Connection:   {dev.connection_type}")
        print(f"USB VID:PID:  {dev.usb_vid}:{dev.usb_pid}")
        print(f"Properties:   {len(dev.properties)} props")
