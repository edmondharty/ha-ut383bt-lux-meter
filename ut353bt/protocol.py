"""Pure protocol logic for the Uni-T UT353BT sound level meter.

All functions here are free of I/O and fully unit-testable without hardware.

Packet layout (19 bytes):
  [0:2]   AA BB        header magic
  [2:5]   10 01 3B     fixed prefix
  [5]     20           space separator
  [6:11]  ASCII        sound level, right-justified, e.g. " 35.9" or "101.1"
  [11:14] ASCII        unit, e.g. "dBA"
  [14]    3D           '=' separator
  [15:19] uint32 BE    status word

Status word bit positions (bit 0 = MSB of the 32-bit big-endian word):
  bits 5-7    : Speed   (0b100=Fast, 0b011=Slow)
  bit  9      : Battery (1=Low)
  bits 12-13  : Mode    (0b10=Max, 0b01=Min, 0b00=Normal)
  bit  15     : Hold    (1=Hold, 0=Live)
  bit  23     : Battery (1=Low)  — either bit 9 or 23 indicates low battery

Control command format (7 bytes):
  AA BB 04 30 <CMD_BYTE> 01 <CHECKSUM>
  Checksum = (0xAA + 0xBB + 0x04 + 0x30 + CMD_BYTE + 0x01 - 1) & 0xFF

Command bytes (reverse-engineered from PacketLogger capture):
  0x44 → Set Slow response
  0x43 → Set Fast response
  0x3F → Activate Max-hold  (Normal → Max)
  0x40 → Advance mode       (Max → Min, or Min → Normal)
  0x42 → Toggle Hold        (live → frozen, or frozen → live)

The device acknowledges every control command with:
  AA BB 04 FF 00 02 68
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum
from typing import Optional

# ── Packet constants ───────────────────────────────────────────────────────────
PACKET_LENGTH = 19
VALUE_START   = 6
VALUE_LENGTH  = 5
HEADER        = (0xAA, 0xBB)

# ── Query command (poll) ───────────────────────────────────────────────────────
CMD_QUERY = bytes([0x5E])

# ── Acknowledgement sent by the device after every control command ─────────────
ACK_PACKET = bytes([0xAA, 0xBB, 0x04, 0xFF, 0x00, 0x02, 0x68])


# ── Enumerations ───────────────────────────────────────────────────────────────
class Speed(str, Enum):
    FAST    = "Fast"
    SLOW    = "Slow"
    UNKNOWN = "Unknown"


class Mode(str, Enum):
    NORMAL  = "Normal"
    MAX     = "Max"
    MIN     = "Min"
    UNKNOWN = "Unknown"


# ── Data class ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SoundReading:
    """A single parsed measurement from the UT353BT."""
    sound_dba:   float
    unit:        str
    hold:        bool
    low_battery: bool
    mode:        Mode
    speed:       Speed
    status_word: int    # raw 32-bit status word, useful for debugging

    def __str__(self) -> str:
        hold_str = "HOLD" if self.hold else "live"
        batt_str = "LOW"  if self.low_battery else "OK"
        return (
            f"{self.sound_dba:>6.1f} {self.unit}"
            f"  speed={self.speed.value:<4}"
            f"  mode={self.mode.value:<6}"
            f"  hold={hold_str:<4}"
            f"  batt={batt_str}"
        )


# ── Command builder ────────────────────────────────────────────────────────────
def make_cmd(cmd_byte: int) -> bytes:
    """Build a 7-byte control command packet for the given command byte.

    Format: AA BB 04 30 <CMD_BYTE> 01 <CHECKSUM>
    Checksum = (0xAA + 0xBB + 0x04 + 0x30 + CMD_BYTE + 0x01 - 1) & 0xFF
    """
    checksum = (0xAA + 0xBB + 0x04 + 0x30 + cmd_byte + 0x01 - 1) & 0xFF
    return bytes([0xAA, 0xBB, 0x04, 0x30, cmd_byte, 0x01, checksum])


# Pre-built control commands
CMD_SLOW = make_cmd(0x44)  # Switch to Slow response mode
CMD_FAST = make_cmd(0x43)  # Switch to Fast response mode
CMD_MAX  = make_cmd(0x3F)  # Activate Max-hold  (Normal → Max)
CMD_MIN  = make_cmd(0x40)  # Advance mode       (Max → Min, or Min → Normal)
CMD_HOLD = make_cmd(0x42)  # Toggle Hold        (live ↔ frozen)


# ── Packet parser ──────────────────────────────────────────────────────────────
def parse_packet(data: bytes | bytearray) -> Optional[SoundReading]:
    """Parse a notification packet into a SoundReading.

    The device occasionally sends packets longer than 19 bytes (e.g. 26 bytes)
    on initial subscription — these appear to be the same 19-byte payload with
    extra trailing bytes.  Any packet of *at least* 19 bytes whose first 19
    bytes form a valid reading is accepted; extra trailing bytes are ignored.

    Returns None if *data* is not a valid measurement packet (too short,
    wrong header, or unparseable sound value).
    """
    if len(data) < PACKET_LENGTH:
        return None
    if data[0] != HEADER[0] or data[1] != HEADER[1]:
        return None

    try:
        sound_str = bytes(data[VALUE_START:VALUE_START + VALUE_LENGTH]).decode("ascii").strip()
        sound_dba = float(sound_str)
    except (ValueError, UnicodeDecodeError):
        return None

    unit   = bytes(data[11:14]).decode("ascii", errors="replace")
    status = struct.unpack(">I", bytes(data[15:19]))[0]

    # Bit positions are counted from the MSB (bit 0 = MSB of the 32-bit word).
    # Python's >> shifts from the LSB, so bit N from MSB = bit (31-N) from LSB.
    hold        = bool((status >> (31 - 15)) & 1)
    low_battery = bool(((status >> (31 -  9)) & 1) | ((status >> (31 - 23)) & 1))
    mode_bits   = (status >> (31 - 13)) & 0b11   # bits 12-13 → 2-bit field
    speed_bits  = (status >> (31 -  7)) & 0b111  # bits  5-7  → 3-bit field

    mode_map  = {0b10: Mode.MAX,  0b01: Mode.MIN,  0b00: Mode.NORMAL}
    speed_map = {0b100: Speed.FAST, 0b011: Speed.SLOW}

    return SoundReading(
        sound_dba   = sound_dba,
        unit        = unit,
        hold        = hold,
        low_battery = low_battery,
        mode        = mode_map.get(mode_bits,  Mode.UNKNOWN),
        speed       = speed_map.get(speed_bits, Speed.UNKNOWN),
        status_word = status,
    )


def is_ack(data: bytes | bytearray) -> bool:
    """Return True if *data* is the device's control-command acknowledgement."""
    return bytes(data) == ACK_PACKET
