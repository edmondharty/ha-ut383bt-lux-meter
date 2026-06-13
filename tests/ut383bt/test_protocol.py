"""Unit tests for ut383bt.protocol — pure logic, no BLE hardware required.

All test packets are taken verbatim from an Android btsnoop HCI capture of the
official Uni-T app talking to a UT383BT (notifications on characteristic 0xff02,
recorded while the meter read ~71–159 lux).

Frame layout reminder (19 bytes):
  [0:2]   AA BB        header
  [2:5]   10 01 3A     prefix
  [6:11]  ASCII        value, right-justified, e.g. "  158"
  [11:14] ASCII        unit, "LUX"
  [14]    3B           ';'
  [15:19] uint32 BE    status word (e.g. 0x30000412)
"""
import pytest

from custom_components.ut383bt.protocol import (
    CMD_QUERY,
    LuxReading,
    parse_packet,
)


def pkt(hex_str: str) -> bytearray:
    """Convert a compact hex string to a bytearray."""
    return bytearray(bytes.fromhex(hex_str.replace(" ", "")))


# ── Known-good packets from the btsnoop capture ───────────────────────────────
# Each entry: (label, hex_packet, lux, status_word)
KNOWN_PACKETS = [
    ("158 lux", "aabb10013a2020203135384c55583b30000412", 158.0, 0x30000412),
    ("159 lux", "aabb10013a2020203135394c55583b30000413", 159.0, 0x30000413),
    ("157 lux", "aabb10013a2020203135374c55583b30000411", 157.0, 0x30000411),
    ("156 lux", "aabb10013a2020203135364c55583b30000410", 156.0, 0x30000410),
    ("153 lux", "aabb10013a2020203135334c55583b3000040d", 153.0, 0x3000040d),
    ("147 lux", "aabb10013a2020203134374c55583b30000410", 147.0, 0x30000410),
    ("135 lux", "aabb10013a2020203133354c55583b3000040d", 135.0, 0x3000040d),
    ("112 lux", "aabb10013a2020203131324c55583b30000408", 112.0, 0x30000408),
    ("91 lux",  "aabb10013a2020202039314c55583b300003fe", 91.0,  0x300003fe),
    ("71 lux",  "aabb10013a2020202037314c55583b300003fc", 71.0,  0x300003fc),
]

# The very first notification on subscribe is overlong (26 bytes) — same payload
# with extra trailing bytes that must be ignored.
OVERLONG_158 = "aabb10013a2020203135384c55583b3000041230000416000000"


class TestParsePacket:

    @pytest.mark.parametrize("label,hex_pkt,lux,status", KNOWN_PACKETS)
    def test_known_packets(self, label, hex_pkt, lux, status):
        result = parse_packet(pkt(hex_pkt))
        assert result is not None, f"{label}: parse_packet returned None"
        assert result.illuminance == pytest.approx(lux, abs=0.05), f"{label}: value"
        assert result.unit == "LUX", f"{label}: unit"
        assert result.status_word == status, f"{label}: status word"

    def test_parses_overlong_packet(self):
        result = parse_packet(pkt(OVERLONG_158))
        assert result is not None
        assert result.illuminance == pytest.approx(158.0, abs=0.05)
        assert result.unit == "LUX"

    def test_status_word_stored(self):
        result = parse_packet(pkt("aabb10013a2020203135384c55583b30000412"))
        assert result is not None
        assert result.status_word == 0x30000412

    def test_returns_none_for_short_packet(self):
        assert parse_packet(bytearray(16)) is None

    def test_returns_none_for_empty(self):
        assert parse_packet(bytearray()) is None

    def test_returns_none_for_wrong_header(self):
        data = pkt("aabb10013a2020203135384c55583b30000412")
        data[0] = 0x00
        assert parse_packet(data) is None

    def test_returns_none_for_bad_ascii_value(self):
        data = pkt("aabb10013a2020203135384c55583b30000412")
        data[6:11] = b"\xFF\xFF\xFF\xFF\xFF"
        assert parse_packet(data) is None

    def test_returns_none_for_non_numeric_value(self):
        data = pkt("aabb10013a2020203135384c55583b30000412")
        data[6:11] = b"xxxxx"
        assert parse_packet(data) is None

    def test_accepts_bytes_and_bytearray(self):
        hex_str = "aabb10013a2020203135384c55583b30000412"
        assert parse_packet(bytearray(bytes.fromhex(hex_str))) is not None
        assert parse_packet(bytes.fromhex(hex_str)) is not None

    def test_reading_is_immutable(self):
        result = parse_packet(pkt("aabb10013a2020203135384c55583b30000412"))
        assert result is not None
        with pytest.raises((AttributeError, TypeError)):
            result.illuminance = 0.0  # type: ignore[misc]

    def test_str_representation(self):
        result = parse_packet(pkt("aabb10013a2020203135384c55583b30000412"))
        assert result is not None
        s = str(result)
        assert "158" in s
        assert "LUX" in s


class TestCmdQuery:

    def test_cmd_query_is_single_byte(self):
        # The app drives the stream by writing 0x5E to the write characteristic.
        assert CMD_QUERY == bytes([0x5E])
