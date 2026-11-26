"""Tests for Samsung Odin/Loke protocol client."""
import struct
from unittest.mock import MagicMock, patch

import pytest

from tools.odin_client import (
    OdinClient,
    PitEntry,
    PitFile,
    detect_samsung_download,
)


class TestPitParsing:
    """Test PIT file binary parsing logic."""

    def _make_pit_header(self, entry_count=2, cpu_tag="LSI3830"):
        """Build a minimal PIT header (32 bytes)."""
        unknown = b"COM_TAR2"  # 8 bytes
        tag = cpu_tag.encode("ascii")[:8].ljust(8, b"\x00")
        logic_units = struct.pack("<I", 0)
        return struct.pack("<I", entry_count) + unknown + tag + logic_units

    def _make_pit_entry(self, name="PERSISTENT", bin_type=0, dev_type=2,
                        identifier=80, attrs=2, blocks=8192):
        """Build a minimal 132-byte PIT entry."""
        header = struct.pack(
            "<9I", bin_type, dev_type, identifier, attrs, 0,
            0, blocks, 0, 0
        )
        # Pad partition name to 16 bytes
        pname = name.encode("ascii")[:16].ljust(16, b"\x00")
        fname = b"\x00" * 16
        fota = b"\x00" * 16
        entry = header + pname + fname + fota
        # Pad to 132 bytes
        entry = entry.ljust(132, b"\x00")
        return entry

    def test_parse_pit_header(self):
        """PIT header is correctly parsed."""
        data = self._make_pit_header(entry_count=3, cpu_tag="LSI3830")
        client = OdinClient()
        pit = client._parse_pit(data)
        assert pit is not None
        assert pit.entry_count == 3
        assert pit.cpu_tag == "LSI3830"

    def test_parse_pit_entries(self):
        """PIT entries are parsed correctly."""
        header = self._make_pit_header(entry_count=2)
        entry1 = self._make_pit_entry(name="PERSISTENT", identifier=80, blocks=8192)
        entry2 = self._make_pit_entry(name="FRP", identifier=85, blocks=4096)
        data = header + entry1 + entry2

        client = OdinClient()
        pit = client._parse_pit(data)
        assert pit is not None
        assert len(pit.entries) == 2
        assert pit.entries[0].partition_name == "PERSISTENT"
        assert pit.entries[0].block_count == 8192
        assert pit.entries[1].partition_name == "FRP"
        assert pit.entries[1].identifier == 85

    def test_pit_too_short(self):
        """Short PIT data returns None."""
        client = OdinClient()
        result = client._parse_pit(b"\x00" * 10)
        assert result is None

    def test_find_frp_partitions(self):
        """find_frp_partitions finds relevant partitions."""
        pit = PitFile(entry_count=3, unknown_string="", cpu_tag="LSI3830", logic_unit_count=0)
        pit.entries = [
            PitEntry(0, 2, 80, 2, 0, 0, 8192, 0, 0, "BOOT", "", ""),
            PitEntry(0, 2, 85, 2, 0, 0, 4096, 0, 0, "PERSISTENT", "", ""),
            PitEntry(0, 2, 90, 2, 0, 0, 2048, 0, 0, "FRP", "", ""),
        ]
        frp = pit.find_frp_partitions()
        assert len(frp) == 2
        names = [e.partition_name for e in frp]
        assert "PERSISTENT" in names
        assert "FRP" in names

    def test_find_partition_case_insensitive(self):
        """find_partition is case-insensitive."""
        pit = PitFile(entry_count=1, unknown_string="", cpu_tag="", logic_unit_count=0)
        pit.entries = [PitEntry(0, 2, 80, 2, 0, 0, 8192, 0, 0, "Persistent", "", "")]
        result = pit.find_partition("persist")
        assert result is not None
        assert result.partition_name == "Persistent"

    def test_is_read_only(self):
        """is_read_only checks attributes field."""
        entry_ro = PitEntry(0, 2, 80, 2, 0, 0, 8192, 0, 0, "BOOT", "", "")
        entry_rw = PitEntry(0, 2, 80, 0, 0, 0, 8192, 0, 0, "DATA", "", "")
        assert entry_ro.is_read_only is True
        assert entry_rw.is_read_only is False

    def test_size_bytes(self):
        """size_bytes = block_count * 512."""
        entry = PitEntry(0, 2, 80, 2, 0, 0, 100, 0, 0, "TEST", "", "")
        assert entry.size_bytes == 100 * 512


class TestDetectSamsungDownload:
    """Test device detection."""

    @patch("tools.odin_client.usb.core.find")
    def test_detect_found(self, mock_find):
        mock_find.return_value = MagicMock()
        assert detect_samsung_download() is True

    @patch("tools.odin_client.usb.core.find")
    def test_detect_not_found(self, mock_find):
        mock_find.return_value = None
        assert detect_samsung_download() is False
