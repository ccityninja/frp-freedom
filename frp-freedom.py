#!/usr/bin/env python3
"""
FRP Freedom — Unified FRP Bypass Tool
A free, self-hosted alternative to commercial FRP tools.

Usage:
  frp-freedom detect                    # Auto-detect connected device
  frp-freedom methods                    # Show available methods for detected device
  frp-freedom unlock                     # Execute best FRP bypass method
  frp-freedom unlock --tool mtkclient    # Force specific tool
  frp-freedom unlock --dry-run           # Show what would happen
  frp-freedom loaders                    # List indexed firehose loaders
  frp-freedom loaders --chipset sm8550   # Filter by chipset
  frp-freedom loaders --scan             # Re-scan collection
  frp-freedom backup                     # Backup FRP partition before erasing
  frp-freedom status                     # Show tool inventory + loader stats
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.detector import DeviceDetector, DeviceInfo, identify_chipset
from core.loader_db import LoaderDB
from core.method_selector import BypassMethod, MethodSelector
from tools.wrappers import get_executor
from app.tool_inventory import tool_status

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("frp-freedom")

# ─── ANSI colors ───
class C:
    R = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def print_header(title: str):
    print(f"\n{C.BOLD}{C.CYAN}{'═' * 60}{C.R}")
    print(f"{C.BOLD}{C.CYAN}  {title}{C.R}")
    print(f"{C.BOLD}{C.CYAN}{'═' * 60}{C.R}\n")


def print_device(dev: DeviceInfo):
    """Pretty-print detected device"""
    print(f"  {C.BOLD}Brand:{C.R}        {dev.brand or 'unknown'}")
    print(f"  {C.BOLD}Model:{C.R}        {dev.model or 'unknown'}")
    print(f"  {C.BOLD}Chipset:{C.R}      {dev.chipset or 'unknown'}")
    print(f"  {C.BOLD}Android:{C.R}      {dev.android_version or 'unknown'}")
    print(f"  {C.BOLD}SPL:{C.R}          {dev.security_patch or 'unknown'}")
    print(f"  {C.BOLD}Connection:{C.R}   {dev.connection_type}")
    print(f"  {C.BOLD}Serial:{C.R}       {dev.serial or 'n/a'}")
    print(f"  {C.BOLD}USB:{C.R}          {dev.usb_vid}:{dev.usb_pid}" if dev.usb_vid else "")


def print_method(m: BypassMethod, idx: int):
    """Pretty-print a bypass method"""
    rate_color = C.GREEN if m.success_rate >= 0.75 else C.YELLOW if m.success_rate >= 0.5 else C.RED
    req_str = ", ".join(m.requires) if m.requires else "none"
    print(f"\n  {C.BOLD}[{idx}]{C.R} {C.BLUE}{m.tool}{C.R}.{C.YELLOW}{m.function}{C.R}")
    print(f"      Priority:    {m.priority}")
    print(f"      Success est: {rate_color}{m.success_rate:.0%}{C.R}")
    print(f"      Requires:    {req_str}")
    if m.params:
        print(f"      Params:      {json.dumps(m.params)}")


def cmd_detect(args):
    """Detect connected devices"""
    print_header("DEVICE DETECTION")
    detector = DeviceDetector()
    devices = detector.detect_all()

    if not devices:
        print(f"  {C.RED}No devices detected.{C.R}")
        print(f"\n  {C.GRAY}Check:{C.R}")
        print("    • USB cable is data-capable (not charge-only)")
        print("    • Device is in the right mode (ADB/BROM/EDL/Download)")
        print("    • udev rules are set for your device")
        print("    • Try: lsusb to see USB devices")
        return None

    for i, dev in enumerate(devices):
        dev.chipset = identify_chipset(dev)
        print(f"\n  {C.BOLD}Device {i + 1}:{C.R}")
        print_device(dev)

    return devices


def cmd_methods(args):
    """Show available methods for detected device"""
    print_header("AVAILABLE FRP BYPASS METHODS")

    # Detect device first
    detector = DeviceDetector()
    devices = detector.detect_all()

    if not devices:
        print(f"  {C.RED}No device detected. Connect a device first.{C.R}")
        return

    dev = devices[0]
    dev.chipset = identify_chipset(dev)
    print(f"  Detected: {C.BOLD}{dev.brand} {dev.model}{C.R} ({dev.chipset}, {dev.connection_type})\n")

    # Get methods
    selector = MethodSelector()
    dev_dict = asdict(dev)
    methods = selector.select_methods(dev_dict)

    if not methods:
        print(f"  {C.RED}No methods available for this device/configuration.{C.R}")
        print(f"\n  {C.GRAY}Try a different connection mode (BROM/EDL/Download).{C.R}")
        return

    print(f"  {C.GREEN}{len(methods)} methods available:{C.R}")
    for i, m in enumerate(methods):
        print_method(m, i + 1)

    # Check for loaders if Qualcomm
    if dev.connection_type == "edl" or "sm" in (dev.chipset or "").lower():
        db = LoaderDB()
        db.load_index() or db.scan()
        loaders = db.find_loader(chipset=dev.chipset, loader_type="firehose")
        if loaders:
            print(f"\n  {C.GREEN}📋 Loaders available for {dev.chipset}:{C.R}")
            for l in loaders[:5]:
                v = "✓" if l.verified else "?"
                print(f"    [{v}] {l.filename} ({l.file_size // 1024}KB) {l.bit_level and f'BIT{l.bit_level}' or ''}")
        else:
            print(f"\n  {C.YELLOW}⚠ No loaders indexed for {dev.chipset}.{C.R}")
            print(f"  {C.GRAY}Run: frp-freedom loaders --scan{C.R}")


def cmd_unlock(args):
    """Execute FRP bypass"""
    print_header("FRP BYPASS EXECUTION")

    # Detect device
    detector = DeviceDetector()
    devices = detector.detect_all()
    if not devices:
        print(f"  {C.RED}No device detected.{C.R}")
        return

    dev = devices[0]
    dev.chipset = identify_chipset(dev)
    print(f"  Device: {C.BOLD}{dev.brand} {dev.model}{C.R} ({dev.chipset}, {dev.connection_type})\n")

    # Get methods
    selector = MethodSelector()
    dev_dict = asdict(dev)
    methods = selector.select_methods(dev_dict)

    if not methods:
        print(f"  {C.RED}No methods available.{C.R}")
        return

    # Select method
    if args.tool:
        methods = [m for m in methods if m.tool == args.tool]
        if not methods:
            print(f"  {C.RED}Tool '{args.tool}' has no applicable methods for this device.{C.R}")
            return

    method = methods[0]
    print(f"  {C.BOLD}Selected method:{C.R} {method.tool}.{method.function}")
    print(f"  {C.BOLD}Success estimate:{C.R} {method.success_rate:.0%}")
    print(f"  {C.BOLD}Requires:{C.R} {', '.join(method.requires)}")

    if args.dry_run:
        print(f"\n  {C.YELLOW}DRY RUN — nothing will be modified.{C.R}")
        print(f"  Would execute: {method.tool}.{method.function}")
        print(f"  With params: {json.dumps(method.params)}")
        return

    # Safety confirmation
    if not args.yes:
        print(f"\n  {C.YELLOW}⚠ This will modify device state (erase FRP partition).{C.R}")
        print(f"  {C.YELLOW}  A backup is recommended before proceeding.{C.R}")
        confirm = input(f"  Type {C.BOLD}ERASE{C.R} to confirm: ")
        if confirm != "ERASE":
            print(f"  {C.GRAY}Aborted.{C.R}")
            return

    # Execute
    executor = get_executor(method.tool)
    if executor is None:
        print(f"  {C.RED}Tool '{method.tool}' is not installed.{C.R}")
        print(f"  {C.GRAY}Run: frp-freedom status{C.R}")
        return

    print(f"\n  {C.CYAN}Executing...{C.R}")
    start = time.time()
    call = {"function": method.function, **method.params}
    result = executor.execute(dev_dict, call)
    duration = time.time() - start

    if result.success:
        print(f"\n  {C.GREEN}✅ SUCCESS in {duration:.1f}s{C.R}")
        if result.output:
            # Show last 500 chars of output
            output = result.output[-500:] if len(result.output) > 500 else result.output
            print(f"\n  {C.GRAY}Output:{C.R}\n{output}")
    else:
        print(f"\n  {C.RED}❌ FAILED in {duration:.1f}s{C.R}")
        if result.error:
            print(f"\n  {C.RED}Error:{C.R} {result.error[-500:]}")

    # Try next method if auto and this failed
    if not result.success and not args.tool and len(methods) > 1:
        print(f"\n  {C.YELLOW}Trying next method...{C.R}")
        # Could iterate through remaining methods


def cmd_loaders(args):
    """List and manage firehose loaders"""
    print_header("FIREHOSE LOADER DATABASE")

    db = LoaderDB()

    if args.scan:
        print(f"  {C.CYAN}Scanning {db.collection_root}...{C.R}")
        loaders = db.scan()
    elif not db.load_index():
        print(f"  {C.CYAN}No index found, scanning...{C.R}")
        loaders = db.scan()
    else:
        loaders = db.loaders

    if not loaders:
        print(f"  {C.RED}No loaders found in {db.collection_root}{C.R}")
        return

    # Filter
    filtered = loaders
    if args.chipset:
        filtered = [l for l in filtered if args.chipset.lower() in l.chipset.lower()]
    if args.brand:
        filtered = [l for l in filtered if args.brand.lower() in l.brand.lower()]
    if args.bit:
        filtered = [l for l in filtered if l.bit_level == args.bit]

    # Stats
    stats = db.stats()
    print(f"  {C.BOLD}Total loaders:{C.R} {stats['total_loaders']}")
    print(f"  {C.BOLD}Verified:{C.R}      {stats['verified']}")
    print(f"  {C.BOLD}By type:{C.R}       {stats['by_type']}")

    print(f"\n  {C.BOLD}By chipset:{C.R}")
    for chip, count in stats['by_chipset'].items():
        print(f"    {chip:20s} {count}")

    print(f"\n  {C.BOLD}Filtered ({len(filtered)}):{C.R}")
    for l in filtered[:50]:
        v = f"{C.GREEN}✓{C.R}" if l.verified else f"{C.GRAY}?{C.R}"
        bit = f" BIT{l.bit_level}" if l.bit_level else ""
        print(f"  {v} {l.filename:40s} {l.chipset:15s} {l.brand:10s}{bit} {l.file_size // 1024}KB")

    if len(filtered) > 50:
        print(f"\n  {C.GRAY}... and {len(filtered) - 50} more{C.R}")


def cmd_status(args):
    """Show tool inventory and system status"""
    print_header("FRP FREEDOM — SYSTEM STATUS")

    # Tool inventory
    tools = tool_status()
    print(f"  {C.BOLD}Tool Inventory:{C.R}\n")
    for t in tools:
        status_color = C.GREEN if t.get("installed") else C.RED
        status = "✓ installed" if t.get("installed") else "✗ not installed"
        print(f"    {status_color}{status}{C.R}  {t['id']:20s} {t.get('detail', '')}")

    # Loader stats
    db = LoaderDB()
    if db.load_index():
        stats = db.stats()
        print(f"\n  {C.BOLD}Loader Database:{C.R}")
        print(f"    Total: {stats['total_loaders']}  Verified: {stats['verified']}")
        print(f"    Types: {stats['by_type']}")

    # Method DB stats
    selector = MethodSelector()
    total = sum(len(v) for v in selector.methods_db.values())
    print(f"\n  {C.BOLD}Method Database:{C.R}")
    print(f"    Total methods: {total}")
    for family, methods in sorted(selector.methods_db.items()):
        print(f"    {family:15s} {len(methods)} methods")

    # Android SDK
    sdk_path = Path.home() / "android-sdk"
    if sdk_path.exists():
        print(f"\n  {C.BOLD}Android SDK:{C.R} {C.GREEN}✓ installed{C.R} at {sdk_path}")
    else:
        print(f"\n  {C.BOLD}Android SDK:{C.R} {C.RED}✗ not installed{C.R}")

    # Zygote toolkit
    zygote = Path.home() / "frp-tools" / "zygote-cve-2024-31317"
    if zygote.exists():
        print(f"  {C.BOLD}Zygote toolkit:{C.R} {C.GREEN}✓ installed{C.R} at {zygote}")
    else:
        print(f"  {C.BOLD}Zygote toolkit:{C.R} {C.RED}✗ not installed{C.R}")


def cmd_backup(args):
    """Backup FRP partition before erasing"""
    print_header("FRP PARTITION BACKUP")

    detector = DeviceDetector()
    devices = detector.detect_all()
    if not devices:
        print(f"  {C.RED}No device detected.{C.R}")
        return

    dev = devices[0]
    dev.chipset = identify_chipset(dev)
    print(f"  Device: {C.BOLD}{dev.brand} {dev.model}{C.R} ({dev.connection_type})\n")

    # Route to appropriate backup tool
    if dev.connection_type == "brom" or "mt" in (dev.chipset or "").lower():
        print(f"  {C.CYAN}Using mtkclient to backup FRP partition...{C.R}")
        executor = get_executor("mtkclient")
        if executor:
            result = executor.execute(asdict(dev), {"function": "read_partitions", "partitions": ["frp", "persist"]})
            if result.success:
                print(f"  {C.GREEN}✅ Backup complete{C.R}")
                for a in result.artifacts:
                    print(f"    📁 {a}")
            else:
                print(f"  {C.RED}❌ Backup failed: {result.error}{C.R}")
        else:
            print(f"  {C.RED}mtkclient not installed{C.R}")

    elif dev.connection_type == "edl" or "sm" in (dev.chipset or "").lower():
        print(f"  {C.CYAN}Using edl to backup FRP partition...{C.R}")
        executor = get_executor("edl")
        if executor:
            result = executor.execute(asdict(dev), {"function": "read_partitions", "partitions": ["frp", "persist"]})
            if result.success:
                print(f"  {C.GREEN}✅ Backup complete{C.R}")
                for a in result.artifacts:
                    print(f"    📁 {a}")
            else:
                print(f"  {C.RED}❌ Backup failed: {result.error}{C.R}")
        else:
            print(f"  {C.RED}edl not installed{C.R}")
    else:
        print(f"  {C.YELLOW}Backup not implemented for {dev.connection_type} mode.{C.R}")


def cmd_samsung(args):
    """Samsung Download mode operations"""
    from tools.odin_client import detect_samsung_download, get_pit_and_frp_partitions, OdinClient

    print(f"\n  {C.BOLD}Samsung Download Mode{C.R}\n")

    if not detect_samsung_download():
        print(f"  {C.RED}No Samsung download mode device found.{C.R}")
        print(f"  {C.GRAY}Put phone in download mode: power off → hold Vol Down → plug USB cable{C.R}")
        return 1

    print(f"  {C.GREEN}✓ Download mode device detected (04e8:685d){C.R}\n")

    if args.action == "pit":
        print(f"  {C.BOLD}Reading PIT file...{C.R} (single session)\n")
        pit, frp_parts = get_pit_and_frp_partitions()
        if not pit:
            print(f"  {C.RED}Failed to read PIT.{C.R}")
            return 1

        print(f"  CPU: {C.YELLOW}{pit.cpu_tag}{C.R}")
        print(f"  Partitions: {pit.entry_count}")
        print(f"  Logic units: {pit.logic_unit_count}\n")

        for e in pit.entries:
            ro = f" {C.GRAY}(RO){C.R}" if e.is_read_only else ""
            print(f"    {e.partition_name:20s} {e.size_bytes:>10,} bytes  id={e.identifier:3d}  blocks={e.block_count}{ro}")

        print(f"\n  {C.BOLD}FRP-related partitions:{C.R}")
        if frp_parts:
            for p in frp_parts:
                print(f"    {C.RED}⚠ {p.partition_name}{C.R}: {p.size_bytes:,} bytes")
        else:
            print(f"    {C.GRAY}None found in PIT{C.R}")

    elif args.action == "backup":
        print(f"  {C.BOLD}Backing up FRP partitions...{C.R}\n")
        pit, frp_parts = get_pit_and_frp_partitions()
        if not pit or not frp_parts:
            print(f"  {C.RED}No PIT or FRP partitions found.{C.R}")
            return 1
        # TODO: implement backup via odin_client.read_partition
        print(f"  {C.YELLOW}Backup not yet implemented — use Heimdall for now:{C.R}")
        for p in frp_parts:
            print(f"    heimdall dump --part {p.partition_name} --output backups/{p.partition_name}.bin")

    elif args.action == "erase":
        print(f"  {C.BOLD}Erase FRP partitions...{C.R}\n")
        pit, frp_parts = get_pit_and_frp_partitions()
        if not pit or not frp_parts:
            print(f"  {C.RED}No PIT or FRP partitions found.{C.R}")
            return 1
        print(f"  {C.YELLOW}Erase via Odin protocol not yet implemented.{C.R}")
        print(f"  {C.GRAY}Identified FRP partitions to erase:{C.R}")
        for p in frp_parts:
            print(f"    {p.partition_name} ({p.size_bytes:,} bytes)")
        print(f"\n  {C.GRAY}Use Heimdall on Linux or Odin on Windows to flash zeroed partitions.{C.R}")

    print()
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="frp-freedom",
        description="🔥 FRP Freedom — Free unified FRP bypass tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # detect
    sub.add_parser("detect", help="Auto-detect connected device")

    # methods
    sub.add_parser("methods", help="Show available bypass methods for detected device")

    # unlock
    p_unlock = sub.add_parser("unlock", help="Execute FRP bypass on detected device")
    p_unlock.add_argument("--tool", help="Force a specific tool (e.g. mtkclient, edl)")
    p_unlock.add_argument("--dry-run", action="store_true", help="Show what would happen without executing")
    p_unlock.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    # loaders
    p_loaders = sub.add_parser("loaders", help="List and manage firehose loaders")
    p_loaders.add_argument("--scan", action="store_true", help="Re-scan collection directory")
    p_loaders.add_argument("--chipset", help="Filter by chipset (e.g. sm8550)")
    p_loaders.add_argument("--brand", help="Filter by brand")
    p_loaders.add_argument("--bit", help="Filter by Samsung BIT level")

    # backup
    sub.add_parser("backup", help="Backup FRP partition before erasing")

    # status
    sub.add_parser("status", help="Show tool inventory and system status")

    # samsung — Samsung Download mode operations
    p_samsung = sub.add_parser("samsung", help="Samsung Download mode operations (Odin/Loke protocol)")
    p_samsung.add_argument("action", choices=["pit", "backup", "erase"], help="pit=read PIT, backup=backup FRP parts, erase=erase FRP parts")

    args = parser.parse_args()

    if args.command == "detect":
        cmd_detect(args)
    elif args.command == "methods":
        cmd_methods(args)
    elif args.command == "unlock":
        cmd_unlock(args)
    elif args.command == "loaders":
        cmd_loaders(args)
    elif args.command == "backup":
        cmd_backup(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "samsung":
        cmd_samsung(args)
    else:
        parser.print_help()
        print(f"\n  {C.GRAY}Run 'frp-freedom detect' to start.{C.R}")


if __name__ == "__main__":
    main()
