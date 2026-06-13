"""Pure protocol logic for the Uni-T UT383BT lux meter.

All functions here are free of I/O and fully unit-testable without hardware.

Packet layout (19 bytes), reverse-engineered from an Android btsnoop HCI capture
of the official Uni-T app talking to a UT383BT:

  [0:2]   AA BB        header magic
  [2:5]   10 01 3A     fixed prefix
  [5]     20           space
  [6:11]  ASCII        illuminance value, right-justified, e.g. "  158" or "   91"
  [11:14] ASCII        unit, e.g. "LUX"
  [14]    3B           ';' separator
  [15:19] uint32 BE    status word

This is the same 19-byte frame as the UT353BT sound meter (same value offset
[6:11] and unit offset [11:14]); only the prefix byte ([4]=0x3A vs 0x3B), the
separator ([14]=';' vs '='), the unit string ("LUX" vs "dBA"), and the meaning
of the status word differ.

The meter streams a fresh notification each time the app writes the single-byte
poll command 0x5E to the write characteristic (identical to the UT353BT).

NOTE on the status word: across every captured reading (whole-number lux in the
71–159 range) the status word was 0x300004XX / 0x300003XX — a constant 0x30 high
byte with a checksum-like low half that tracks the value.  Its individual bits
(hold, low-battery, units, range/decade) are NOT decoded here because no capture
exercising those states exists yet; the raw word is preserved on every reading
so it can be decoded later without re-capturing.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

# ── Packet constants ───────────────────────────────────────────────────────────
PACKET_LENGTH = 19
VALUE_START   = 6
VALUE_LENGTH  = 5
UNIT_START    = 11
UNIT_LENGTH   = 3
STATUS_START  = 15
HEADER        = (0xAA, 0xBB)

# ── Query command (poll) ───────────────────────────────────────────────────────
CMD_QUERY = bytes([0x5E])


# ── Data class ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LuxReading:
    """A single parsed measurement from the UT383BT."""
    illuminance: float   # lux
    unit:        str      # e.g. "LUX"
    status_word: int      # raw 32-bit status word at [15:19], bits not yet decoded

    def __str__(self) -> str:
        return f"{self.illuminance:>8.0f} {self.unit}  status=0x{self.status_word:08x}"


# ── Packet parser ──────────────────────────────────────────────────────────────
def parse_packet(data: bytes | bytearray) -> Optional[LuxReading]:
    """Parse a notification packet into a LuxReading.

    The device occasionally sends packets longer than 19 bytes on initial
    subscription (e.g. 26 bytes) — these are the same 19-byte payload with extra
    trailing bytes, which are ignored.  Returns None if *data* is not a valid
    measurement packet (too short, wrong header, or unparseable value).
    """
    if len(data) < PACKET_LENGTH:
        return None
    if data[0] != HEADER[0] or data[1] != HEADER[1]:
        return None

    try:
        value_str = bytes(data[VALUE_START:VALUE_START + VALUE_LENGTH]).decode("ascii").strip()
        illuminance = float(value_str)
    except (ValueError, UnicodeDecodeError):
        return None

    unit   = bytes(data[UNIT_START:UNIT_START + UNIT_LENGTH]).decode("ascii", errors="replace").strip()
    status = struct.unpack(">I", bytes(data[STATUS_START:STATUS_START + 4]))[0]

    return LuxReading(
        illuminance = illuminance,
        unit        = unit,
        status_word = status,
    )
