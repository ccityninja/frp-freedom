# 🔥 FRP Freedom

A free, self-hosted, multi-chipset FRP bypass tool — a community alternative to commercial tools like Chimera Tool.

## What It Does

Plug in a phone → auto-detect chipset/brand/mode → pick the best bypass method → backup → unlock → done. One unified CLI wrapping every free FRP bypass tool into a single interface.

## Quick Start

```bash
# Clone and setup
git clone https://github.com/ccityninja/frp-freedom.git
cd frp-freedom
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Check what's installed
python frp-freedom.py status

# Index your firehose loader collection
python frp-freedom.py loaders --scan

# Detect a connected device
python frp-freedom.py detect

# Show available methods for detected device
python frp-freedom.py methods

# Execute FRP bypass (with confirmation prompt)
python frp-freedom.py unlock

# Dry run (show what would happen)
python frp-freedom.py unlock --dry-run

# Force a specific tool
python frp-freedom.py unlock --tool mtkclient

# List indexed loaders, filter by chipset
python frp-freedom.py loaders --chipset sm8550
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `status` | Show tool inventory, loader stats, method count |
| `detect` | Auto-detect connected device (ADB/Fastboot/EDL/BROM/Download) |
| `methods` | Show ranked bypass methods for detected device |
| `unlock` | Execute best FRP bypass method (auto-selected) |
| `unlock --tool X` | Force a specific tool |
| `unlock --dry-run` | Show what would happen without executing |
| `backup` | Backup FRP partition before erasing |
| `loaders` | List indexed firehose loaders |
| `loaders --scan` | Re-scan collection directory |
| `loaders --chipset X` | Filter loaders by chipset |

## Supported Chipset Families

| Family | Methods | Key Tools |
|--------|---------|-----------|
| **MediaTek** (Helio, Dimensity) | 7 | mtkclient (BROM/preloader), Penumbra (Carbonara/heapb8), Valhalla (Motorola MTK) |
| **Qualcomm** (Snapdragon) | 5 | edl (firehose), Zygote CVE-2024-31317, frp_freedom |
| **Exynos/Samsung** | 7 | nPhoneKIT, SamFw server, Samsung FRP Web, frp_freedom, fu_frp |
| **Unisoc** (Spreadtrum) | 5 | SPD Client, CVE-2022-38694, SPD Research Tool, SPD Flasher APK |
| **Kirin** (Huawei) | 3 | kirin_toolkit, Sigma |
| **Hardware** (ISP/chip-off) | 4 | EasyJTAG+, Medusa Pro II, UFS socket |
| **Unknown** (fallback) | 1 | frp_freedom auto-detect |

**32 methods across 7 families.** Routes automatically based on detected chipset, Android version, security patch level, and connection mode.

## Tool Inventory

FRP Freedom wraps these free/open-source tools:

- **mtkclient** — MediaTek BROM/preloader FRP erase ([github.com/bkerler/mtkclient](https://github.com/bkerler/mtkclient))
- **edl** — Qualcomm EDL firehose ([github.com/bkerler/edl](https://github.com/bkerler/edl))
- **Zygote CVE-2024-31317** — ADB Zygote injection, no root ([github.com/vnescape/zygote-CVE-2024-31317](https://github.com/vnescape/zygote-CVE-2024-31317))
- **Penumbra** — MTK DA exploits (Carbonara, heapb8) ([github.com/shomykohai/penumbra](https://github.com/shomykohai/penumbra))
- **Valhalla** — Motorola MTK bootloader unlock + FRP
- **nPhoneCLI** — Samsung ADB/modem FRP ([github.com/nlckysolutions/nPhoneCLI](https://github.com/nlckysolutions/nPhoneCLI))
- **SPD Client** — Unisoc BROM erase
- **Samsung FRP Web** — Browser-based WebSerial/WebUSB FRP bypass
- **frp-freedom** — Multi-OEM ADB exploits ([github.com/youngrichu/frp-freedom](https://github.com/youngrichu/frp-freedom))

## Loader Database

FRP Freedom indexes your firehose loader collection and auto-matches loaders to detected devices:

```bash
frp-freedom loaders                    # List all indexed loaders
frp-freedom loaders --scan             # Re-scan collection
frp-freedom loaders --chipset sm8550   # Filter by chipset
frp-freedom loaders --brand samsung    # Filter by brand
frp-freedom loaders --bit 5            # Filter by Samsung BIT level
```

Loaders are indexed by sha256, chipset, brand, BIT level, and loader type (firehose/DA). The index is saved as JSON for fast lookups.

## Web Dashboard

```bash
python -m app.server    # Starts at http://127.0.0.1:8484
```

Browser UI with the same detection → method selection → execution flow.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   FRP Freedom CLI                     │
│  frp-freedom.py (detect / methods / unlock / backup)  │
├─────────────┬──────────────┬────────────────────────┤
│  DeviceDetector  │  MethodSelector  │  LoaderDB       │
│  (ADB/FB/EDL/    │  (32 methods,    │  (HWID/PKHash    │
│   BROM/DL)       │   7 families)    │   indexed)       │
├─────────────┴──────────────┴────────────────────────┤
│              Tool Executor Wrappers                   │
│  mtkclient │ edl │ zygote │ spd │ valhalla │ penumbra │
├──────────────────────────────────────────────────────┤
│              Web Dashboard (server.py :8484)          │
└──────────────────────────────────────────────────────┘
```

## Project Structure

```
frp-freedom/
├── frp-freedom.py          # Unified CLI entry point
├── core/
│   ├── detector.py         # Multi-protocol device detection
│   ├── chipset_id.py       # SoC identification from properties
│   ├── method_selector.py  # 32 methods, 7 families, auto-routing
│   └── loader_db.py        # Firehose loader index + query
├── tools/
│   └── wrappers.py         # 19 tool executor classes
├── app/
│   ├── server.py           # Web dashboard (FastAPI :8484)
│   ├── tool_inventory.py   # Auto-detect installed tools
│   └── static/             # Web UI assets
├── tests/
│   └── test_*.py           # 70 tests, all passing
└── requirements.txt
```

## Requirements

- **OS**: Linux (Ubuntu 22.04+/Debian 12/Arch) or Windows 10/11 (WSL2 recommended)
- **Python**: 3.10+
- **USB**: Data-capable cable, udev rules (Linux) or USB-DK (Windows)
- **ADB/Fastboot**: Android platform-tools
- **Optional**: Android SDK build-tools (for Zygote APK compilation)

## Legal / Safety

- **Only run on devices you own or have explicit written authorization for**
- **Backup partitions before erase** (`frp-freedom backup`)
- **All tools run locally** — no cloud calls, no telemetry, no license servers

## References

- [bkerler/mtkclient](https://github.com/bkerler/mtkclient) — MediaTek BROM
- [bkerler/edl](https://github.com/bkerler/edl) — Qualcomm EDL
- [vnescape/zygote-CVE-2024-31317](https://github.com/vnescape/zygote-CVE-2024-31317) — Zygote injection
- [shomykohai/penumbra](https://github.com/shomykohai/penumbra) — MTK DA exploits
- [nlckysolutions/nPhoneCLI](https://github.com/nlckysolutions/nPhoneCLI) — Samsung FRP
- [youngrichu/frp-freedom](https://github.com/youngrichu/frp-freedom) — Multi-OEM ADB exploits
