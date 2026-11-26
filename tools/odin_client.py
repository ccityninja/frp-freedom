#!/usr/bin/env python3
"""
Samsung Odin/Loke USB Protocol Client
Direct USB communication with Samsung devices in Download mode (04e8:685d).
Uses pyusb — no dependency on Heimdall's fragile session management.

Protocol reference: Heimdall source (Glass Echidna), Odin protocol docs.
The Loke/Odin protocol uses bulk transfers on EP1 (IN=0x81, OUT=0x01).

Session flow:
  1. Send BEGIN_SESSION packet (0x64) → device responds with session ack
  2. Send PIT_REQUEST (0x65) → device returns PIT file
  3. Send FILE_READ (0x69) for each partition to read
  4. Send END_SESSION (0x66) to close cleanly

PIT file format (little-endian):
  Header: 4B entry_count, 8B unknown, 8B cpu_tag, 4B logic_unit_count
  Entry (32B each): binary_type, device_type, identifier, attributes,
    update_attributes, partition_block_offset, partition_block_count,
    file_offset, file_size, partition_name[16], flash_filename[16], fota_filename[16]
"""

import logging
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

import usb.core
import usb.util

logger = logging.getLogger(__name__)

SAMSUNG_VID = 0x04E8
DOWNLOAD_PID = 0x685D

# Odin/Loke packet types
PKT_BEGIN_SESSION = 0x64
PKT_END_SESSION = 0x66
PKT_PIT_REQUEST = 0x65
PKT_FILE_READ = 0x69
PKT_FILE_WRITE = 0x6A
PKT_DEVICE_INFO = 0x6B

# Response codes
RESP_ACK = 0x00
RESP_NAK = 0xFF

# PIT entry structure (32 bytes per entry in the PIT file itself, but Odin uses 132-byte entries)
PIT_HEADER_SIZE = 24
PIT_ENTRY_SIZE = 132


@dataclass
class PitEntry:
    """Single PIT partition entry"""
    binary_type: int      # 0=AP, 1=CP, 2=MB
    device_type: int      # 0=OneNAND, 2=MMC/UFS
    identifier: int
    attributes: int
    update_attributes: int
    block_offset: int
    block_count: int
    file_offset: int
    file_size: int
    partition_name: str
    flash_filename: str
    fota_filename: str

    @property
    def is_read_only(self) -> bool:
        return self.attributes == 2  # STL Read-Only

    @property
    def size_bytes(self) -> int:
        return self.block_count * 512  # 512-byte blocks


@dataclass
class PitFile:
    """Parsed Samsung PIT file"""
    entry_count: int
    unknown_string: str
    cpu_tag: str
    logic_unit_count: int
    entries: list[PitEntry] = field(default_factory=list)

    def find_partition(self, name: str) -> PitEntry | None:
        """Find a partition by name (case-insensitive)"""
        for e in self.entries:
            if name.lower() in e.partition_name.lower():
                return e
        return None

    def find_frp_partitions(self) -> list[PitEntry]:
        """Find all FRP-related partitions"""
        frp_names = ["frp", "persistent", "persist", "tz_kg", "kg", "knox", "sec"]
        result = []
        for e in self.entries:
            for name in frp_names:
                if name in e.partition_name.lower():
                    result.append(e)
                    break
        return result


class OdinClient:
    """Direct Samsung Odin/Loke USB protocol client"""

    def __init__(self):
        self.dev = None
        self.ep_out = None
        self.ep_in = None
        self.session_active = False

    def connect(self, timeout_ms: int = 5000) -> bool:
        """Find and connect to Samsung download mode device"""
        self.dev = usb.core.find(idVendor=SAMSUNG_VID, idProduct=DOWNLOAD_PID)
        if self.dev is None:
            logger.error("No Samsung download mode device found (04e8:685d)")
            return False

        # Reset device to clean state
        try:
            self.dev.reset()
        except usb.core.USBError:
            pass  # Some devices don't need reset

        # Get endpoints
        cfg = self.dev.get_active_configuration()
        for intf in cfg:
            for ep in intf:
                if ep.bEndpointAddress & 0x80:
                    self.ep_in = ep  # IN endpoint
                else:
                    self.ep_out = ep  # OUT endpoint

        if not self.ep_in or not self.ep_out:
            logger.error("Could not find bulk endpoints")
            return False

        # Claim interface
        try:
            usb.util.claim_interface(self.dev, 0)
        except usb.core.USBError as e:
            # Try detaching kernel driver
            try:
                if self.dev.is_kernel_driver_active(0):
                    self.dev.detach_kernel_driver(0)
                    usb.util.claim_interface(self.dev, 0)
            except usb.core.USBError:
                logger.error(f"Cannot claim interface: {e}")
                return False

        logger.info("Samsung download mode device connected")
        return True

    def _send_packet(self, pkt_type: int, data: bytes = b"") -> bool:
        """Send an Odin protocol packet"""
        # Odin packet: 4-byte type + data
        packet = struct.pack("<I", pkt_type) + data
        try:
            self.ep_out.write(packet, timeout=5000)
            return True
        except usb.core.USBError as e:
            logger.error(f"Send packet 0x{pkt_type:02x} failed: {e}")
            return False

    def _read_response(self, size: int = 1024, timeout_ms: int = 10000) -> bytes | None:
        """Read response from device"""
        try:
            data = self.ep_in.read(size, timeout=timeout_ms)
            return bytes(data)
        except usb.core.USBError as e:
            logger.error(f"Read response failed: {e}")
            return None

    def begin_session(self) -> bool:
        """Begin Odin session"""
        if not self._send_packet(PKT_BEGIN_SESSION):
            return False
        resp = self._read_response(timeout_ms=10000)
        if resp and len(resp) >= 4:
            resp_type = struct.unpack_from("<I", resp, 0)[0]
            if resp_type == PKT_BEGIN_SESSION:
                self.session_active = True
                logger.info("Odin session begun")
                return True
        logger.error("Session begin failed")
        return False

    def end_session(self) -> bool:
        """End Odin session cleanly"""
        if not self.session_active:
            return True
        result = self._send_packet(PKT_END_SESSION)
        self.session_active = False
        return result

    def get_pit(self) -> PitFile | None:
        """Request and parse PIT file from device"""
        if not self.session_active and not self.begin_session():
            return None

        # Send PIT request
        if not self._send_packet(PKT_PIT_REQUEST):
            return None

        # Read PIT data — may come in multiple packets
        pit_data = b""
        while True:
            resp = self._read_response(size=65536, timeout_ms=15000)
            if not resp or len(resp) < 4:
                break
            resp_type = struct.unpack_from("<I", resp, 0)[0]
            if resp_type == PKT_PIT_REQUEST:
                # PIT data follows
                pit_data = resp[4:]
                break
            elif resp_type == RESP_ACK:
                continue
            else:
                break

        if not pit_data:
            logger.error("No PIT data received")
            return None

        return self._parse_pit(pit_data)

    def _parse_pit(self, data: bytes) -> PitFile | None:
        """Parse PIT file binary data"""
        if len(data) < PIT_HEADER_SIZE:
            logger.error(f"PIT data too short: {len(data)} bytes")
            return None

        # Header
        entry_count = struct.unpack_from("<I", data, 0)[0]
        unknown_str = data[4:12].rstrip(b'\x00').decode('ascii', errors='replace')
        cpu_tag = data[12:20].rstrip(b'\x00').decode('ascii', errors='replace')
        logic_unit_count = struct.unpack_from("<I", data, 20)[0]

        pit = PitFile(
            entry_count=entry_count,
            unknown_string=unknown_str,
            cpu_tag=cpu_tag,
            logic_unit_count=logic_unit_count,
        )

        # Parse entries
        offset = PIT_HEADER_SIZE
        for i in range(entry_count):
            if offset + PIT_ENTRY_SIZE > len(data):
                logger.warning(f"PIT entry {i} truncated at offset {offset}")
                break

            entry_data = data[offset:offset + PIT_ENTRY_SIZE]
            entry = self._parse_pit_entry(entry_data)
            pit.entries.append(entry)
            offset += PIT_ENTRY_SIZE

        logger.info(f"PIT parsed: {pit.entry_count} entries, CPU={pit.cpu_tag}")
        return pit

    def _parse_pit_entry(self, data: bytes) -> PitEntry:
        """Parse a single 132-byte PIT entry"""
        # Binary type (4B), device type (4B), identifier (4B), attributes (4B),
        # update_attributes (4B), block_offset (4B), block_count (4B),
        # file_offset (4B), file_size (4B) = 36 bytes
        (binary_type, device_type, identifier, attributes,
         update_attributes, block_offset, block_count,
         file_offset, file_size) = struct.unpack_from("<9I", data, 0)

        # Partition name (16B starting at offset 36 in Heimdall's format)
        partition_name = data[36:52].rstrip(b'\x00').decode('ascii', errors='replace')
        # Flash filename (16B at 52? Actually Heimdall uses 20B strings)
        # Actually the PIT entry has 3 strings of 16 bytes each in the simplest format
        # But Samsung's newer format uses 20-byte strings
        # Let's try both: first 16-byte, then 20-byte
        flash_filename = data[52:68].rstrip(b'\x00').decode('ascii', errors='replace')
        fota_filename = data[68:84].rstrip(b'\x00').decode('ascii', errors='replace')

        # If strings look wrong, try 20-byte offsets
        if not partition_name and len(data) > 96:
            partition_name = data[36:56].rstrip(b'\x00').decode('ascii', errors='replace')
            flash_filename = data[56:76].rstrip(b'\x00').decode('ascii', errors='replace')
            fota_filename = data[76:96].rstrip(b'\x00').decode('ascii', errors='replace')

        return PitEntry(
            binary_type=binary_type,
            device_type=device_type,
            identifier=identifier,
            attributes=attributes,
            update_attributes=update_attributes,
            block_offset=block_offset,
            block_count=block_count,
            file_offset=file_offset,
            file_size=file_size,
            partition_name=partition_name,
            flash_filename=flash_filename,
            fota_filename=fota_filename,
        )

    def read_partition(self, pit_entry: PitEntry) -> bytes | None:
        """Read a partition's raw data (for backup)"""
        if not self.session_active and not self.begin_session():
            return None

        # Send file read request with partition identifier
        # Format: packet_type + identifier (4B) + size (4B)
        size = pit_entry.size_bytes
        data = struct.pack("<II", pit_entry.identifier, size)
        if not self._send_packet(PKT_FILE_READ, data):
            return None

        # Read partition data in chunks
        result = b""
        remaining = size
        while remaining > 0:
            chunk_size = min(remaining, 65536)
            resp = self._read_response(size=chunk_size + 4, timeout_ms=30000)
            if not resp:
                break
            result += resp[4:]  # Skip 4-byte header
            remaining -= len(resp) - 4

        if len(result) < size:
            logger.warning(f"Short read: {len(result)}/{size} bytes for {pit_entry.partition_name}")
        else:
            logger.info(f"Read {len(result)} bytes from {pit_entry.partition_name}")

        return result

    def get_device_info(self) -> dict:
        """Get device info (model, firmware, etc.)"""
        if not self.session_active and not self.begin_session():
            return {}

        info = {}
        if self._send_packet(PKT_DEVICE_INFO):
            resp = self._read_response(size=4096, timeout_ms=5000)
            if resp and len(resp) > 4:
                info["raw"] = resp.hex()
                # Parse device info fields (model, firmware, etc.)
                # Format varies by device — extract printable strings
                raw = resp[4:]
                strings = []
                current = b""
                for b in raw:
                    if 0x20 <= b < 0x7f:
                        current += bytes([b])
                    else:
                        if len(current) >= 4:
                            strings.append(current.decode('ascii'))
                        current = b""
                if len(current) >= 4:
                    strings.append(current.decode('ascii'))
                info["strings"] = strings
                for s in strings:
                    if s.startswith("SM-"):
                        info["model"] = s
                    elif len(s) == 6 and s[0].isalpha():
                        info["csc"] = s

        return info

    def close(self):
        """Close connection and release USB"""
        if self.session_active:
            self.end_session()
        if self.dev:
            usb.util.release_interface(self.dev, 0)
            usb.util.dispose_resources(self.dev)
            self.dev = None
        self.session_active = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def detect_samsung_download() -> bool:
    """Check if a Samsung download mode device is present"""
    dev = usb.core.find(idVendor=SAMSUNG_VID, idProduct=DOWNLOAD_PID)
    return dev is not None


def get_pit_and_frp_partitions() -> tuple[PitFile | None, list[PitEntry]]:
    """One-shot: connect, get PIT, find FRP partitions, disconnect.
    Returns (pit, frp_partitions) — all in one session to avoid Heimdall's multi-session crash."""
    client = OdinClient()
    try:
        if not client.connect():
            return None, []
        if not client.begin_session():
            return None, []

        pit = client.get_pit()
        if not pit:
            return None, []

        frp_parts = pit.find_frp_partitions()
        logger.info(f"Found {len(frp_parts)} FRP-related partitions")
        for p in frp_parts:
            logger.info(f"  {p.partition_name}: {p.size_bytes} bytes, blocks={p.block_count}, offset={p.block_offset}")

        return pit, frp_parts
    finally:
        client.close()
