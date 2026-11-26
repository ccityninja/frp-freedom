#!/usr/bin/env python3
"""
FRP Bot — Loader Database
Indexes firehose loaders and DA files by HWID/PKHash/chipset.
Auto-matches detected device → available loader.
"""

import hashlib
import json
import logging
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Known USB IDs for device modes
USB_IDS = {
    # Qualcomm EDL
    ("05c6", "9008"): {"mode": "edl", "chipset_family": "qualcomm"},
    ("05c6", "9006"): {"mode": "edl", "chipset_family": "qualcomm"},  # QDLoader
    # MediaTek BROM/Preloader
    ("0e8d", "0003"): {"mode": "brom", "chipset_family": "mediatek"},
    ("0e8d", "2000"): {"mode": "preloader", "chipset_family": "mediatek"},
    ("0e8d", "2001"): {"mode": "preloader", "chipset_family": "mediatek"},
    # Samsung Download mode
    ("04e8", "685d"): {"mode": "download", "chipset_family": "exynos"},
    ("04e8", "9000"): {"mode": "download", "chipset_family": "exynos"},
    # Unisoc BROM
    ("1782", "4d00"): {"mode": "brom", "chipset_family": "unisoc"},
    ("1782", "4d07"): {"mode": "brom", "chipset_family": "unisoc"},
}

# Qualcomm HWID → chipset family mapping (from Sahara handshake)
# Format: (MSM_HW_ID upper 32 bits) → chipset name
QUALCOMM_HWID_MAP = {
    0x007B: "msm8998",      # SD 835
    0x0079: "msm8996",      # SD 820/821
    0x0080: "msm8998",      # SD 835 variant
    0x009F: "sdm845",       # SD 845
    0x00A0: "sdm845",       # SD 845 variant
    0x00AE: "sm8150",       # SD 855
    0x00C4: "sm8250",       # SD 865
    0x00D1: "sm8350",       # SD 888
    0x00DC: "sm8450",       # SD 8 Gen 1
    0x00F4: "sm8550",       # SD 8 Gen 2
    0x0106: "sm8650",       # SD 8 Gen 3
    0x011E: "sm8750",       # SD 8 Elite
    # Mid-range
    0x00AF: "sm6150",       # SD 730
    0x00C8: "sm7150",       # SD 720G
    0x00CB: "sm7225",       # SD 750G
    0x00D8: "sm7250",       # SD 765G
    0x00E1: "sm7325",       # SD 778G
    0x00EF: "sm7450",       # SD 7 Gen 1
    0x00F5: "sm7550",       # SD 7+ Gen 2
    0x00FE: "sm7675",       # SD 7+ Gen 3
    0x0103: "sm7550",       # SD 7 Gen 3
    # Budget
    0x00A7: "qm215",        # SD 215
    0x0090: "msm8937",      # SD 430/435
    0x0095: "msm8917",      # SD 425/427
    0x00A2: "msm8920",      # SD 450
    0x00B0: "msm8937",      # SD 439
    0x00C0: "sm6125",       # SD 680
    0x00D6: "sm6375",       # SD 695
    0x00E8: "sm6450",       # SD 6 Gen 1
    0x00F9: "sm6475",       # SD 6 Gen 3
}


@dataclass
class LoaderEntry:
    """A single firehose loader or DA file in the collection"""
    path: str
    filename: str
    sha256: str
    file_size: int
    chipset: str = ""           # e.g. "sm8550", "mt6789"
    chipset_family: str = ""    # qualcomm, mediatek, etc
    brand: str = ""             # samsung, xiaomi, motorola, generic
    hwid: str = ""              # Qualcomm MSM_HW_ID (hex)
    pkhash: str = ""            # OEM PK_HASH (hex, from Sahara)
    bit_level: str = ""         # Samsung BIT level
    loader_type: str = ""       # firehose, da, preloader
    verified: bool = False      # tested on actual device
    source: str = ""            # where it came from
    notes: str = ""
    tags: list[str] = field(default_factory=list)


class LoaderDB:
    """Indexes and queries firehose loaders / DA files"""

    def __init__(self, collection_root: str = None):
        self.collection_root = Path(collection_root or Path.home() / "firehose_collection")
        self.loaders: list[LoaderEntry] = []
        self.index_path = self.collection_root / "loader_index.json"

    def scan(self) -> list[LoaderEntry]:
        """Scan collection directory for loader files and index them"""
        self.loaders = []
        if not self.collection_root.exists():
            logger.warning(f"Collection root not found: {self.collection_root}")
            return []

        # Supported file extensions
        loader_exts = {".bin", ".elf", ".mbn", ".hex", ".img"}
        da_exts = {".bin", ".raw"}

        for f in self.collection_root.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in loader_exts:
                continue

            entry = self._index_file(f)
            if entry:
                self.loaders.append(entry)

        logger.info(f"Indexed {len(self.loaders)} loaders from {self.collection_root}")
        self._save_index()
        return self.loaders

    def _index_file(self, path: Path) -> LoaderEntry | None:
        """Index a single loader file"""
        try:
            data = path.read_bytes()
            sha256 = hashlib.sha256(data).hexdigest()
            file_size = len(data)

            # Extract metadata from path structure
            rel_path = path.relative_to(self.collection_root)
            parts = rel_path.parts

            chipset = ""
            brand = ""
            bit_level = ""
            loader_type = "firehose"

            # Parse path: sources/qcom_loaders/<chipset>/<bit>/ or sources/mtk_da/<chipset>/
            path_str = str(rel_path).lower()

            # Detect chipset from path
            for chip in QUALCOMM_HWID_MAP.values():
                if chip in path_str:
                    chipset = chip
                    break
            if not chipset:
                # MTK detection from path
                mtk_match = re.search(r'mt[678]\d{3}', path_str)
                if mtk_match:
                    chipset = mtk_match.group()
                    loader_type = "da"

            # Detect brand from path
            brand_map = {
                "samsung": "samsung", "xiaomi": "xiaomi", "motorola": "motorola",
                "oneplus": "oneplus", "oppo": "oppo", "vivo": "vivo",
                "nothing": "nothing", "google": "google", "asus": "asus",
            }
            for b, name in brand_map.items():
                if b in path_str:
                    brand = name
                    break

            # Detect BIT level from path
            bit_match = re.search(r'bit[_-]?(\d+)', path_str, re.IGNORECASE)
            if bit_match:
                bit_level = bit_match.group(1)

            # Detect loader type
            if "preloader" in path_str or "da_" in path_str:
                loader_type = "da"
            elif "firehose" in path_str or "prog_" in path_str:
                loader_type = "firehose"

            # Try to extract HWID from ELF header (Qualcomm firehose)
            hwid = ""
            pkhash = ""
            if data[:4] == b'\x7fELF':
                hwid = self._extract_hwid_from_elf(data)

            return LoaderEntry(
                path=str(path),
                filename=path.name,
                sha256=sha256,
                file_size=file_size,
                chipset=chipset,
                chipset_family="qualcomm" if chipset.startswith("sm") or chipset.startswith("msm") or chipset.startswith("sd") else ("mediatek" if chipset.startswith("mt") else ""),
                brand=brand,
                hwid=hwid,
                pkhash=pkhash,
                bit_level=bit_level,
                loader_type=loader_type,
                source=str(rel_path),
            )
        except Exception as e:
            logger.debug(f"Failed to index {path}: {e}")
            return None

    def _extract_hwid_from_elf(self, data: bytes) -> str:
        """Try to extract HWID from ELF header (Qualcomm-specific)"""
        try:
            # ELF header parsing for ARM 32-bit
            if data[4] != 1:  # EI_CLASS = ELFCLASS32
                return ""
            # e_entry at offset 0x18 (4 bytes LE)
            entry = struct.unpack_from('<I', data, 0x18)[0]
            # Qualcomm firehose often embeds HWID in the binary
            # This is a heuristic — not reliable for all loaders
            return f"0x{entry:08X}"
        except Exception:
            return ""

    def find_loader(self, chipset: str = "", brand: str = "", hwid: str = "",
                    pkhash: str = "", bit_level: str = "",
                    loader_type: str = "") -> list[LoaderEntry]:
        """Find matching loaders for a device"""
        matches = []
        for entry in self.loaders:
            if chipset and entry.chipset and chipset.lower() not in entry.chipset.lower():
                continue
            if brand and entry.brand and brand.lower() not in entry.brand.lower():
                continue
            if hwid and entry.hwid and hwid.lower() not in entry.hwid.lower():
                continue
            if pkhash and entry.pkhash and pkhash.lower() not in entry.pkhash.lower():
                continue
            if bit_level and entry.bit_level and bit_level != entry.bit_level:
                continue
            if loader_type and entry.loader_type and loader_type != entry.loader_type:
                continue
            matches.append(entry)

        # Sort: verified first, then by chipset match specificity
        matches.sort(key=lambda e: (not e.verified, not e.chipset, not e.brand))
        return matches

    def stats(self) -> dict:
        """Return index statistics"""
        by_chipset: dict[str, int] = {}
        by_brand: dict[str, int] = {}
        by_type: dict[str, int] = {}
        verified_count = 0
        for e in self.loaders:
            if e.chipset:
                by_chipset[e.chipset] = by_chipset.get(e.chipset, 0) + 1
            if e.brand:
                by_brand[e.brand] = by_brand.get(e.brand, 0) + 1
            by_type[e.loader_type] = by_type.get(e.loader_type, 0) + 1
            if e.verified:
                verified_count += 1
        return {
            "total_loaders": len(self.loaders),
            "by_chipset": dict(sorted(by_chipset.items())),
            "by_brand": dict(sorted(by_brand.items())),
            "by_type": dict(sorted(by_type.items())),
            "verified": verified_count,
        }

    def _save_index(self) -> None:
        """Save index to JSON for quick loading"""
        data = []
        for e in self.loaders:
            data.append({
                "path": e.path, "filename": e.filename, "sha256": e.sha256,
                "file_size": e.file_size, "chipset": e.chipset,
                "chipset_family": e.chipset_family, "brand": e.brand,
                "hwid": e.hwid, "pkhash": e.pkhash, "bit_level": e.bit_level,
                "loader_type": e.loader_type, "verified": e.verified,
                "source": e.source, "notes": e.notes, "tags": e.tags,
            })
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(data, indent=2))
        logger.info(f"Index saved: {self.index_path}")

    def load_index(self) -> bool:
        """Load previously saved index (faster than full scan)"""
        if not self.index_path.exists():
            return False
        try:
            data = json.loads(self.index_path.read_text())
            self.loaders = [LoaderEntry(**d) for d in data]
            logger.info(f"Loaded {len(self.loaders)} loaders from index")
            return True
        except Exception as e:
            logger.warning(f"Failed to load index: {e}")
            return False


def hwid_to_chipset(hwid_hex: str) -> str:
    """Map Sahara HWID to chipset name"""
    try:
        hwid_int = int(hwid_hex, 16)
        upper32 = (hwid_int >> 32) & 0xFFFF
        return QUALCOMM_HWID_MAP.get(upper32, f"unknown_hwid_{hwid_hex}")
    except Exception:
        return ""
