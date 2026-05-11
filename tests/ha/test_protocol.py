"""Unit tests for ut353bt.protocol — pure logic, no BLE hardware required.

All test packets are taken verbatim from data_captured.txt, which was recorded
by proxying the official iENV app through iOS PacketLogger.

Bit layout reminder (bit 0 = MSB of the 32-bit big-endian status word):
  bits 5-7  : Speed   0b100=Fast, 0b011=Slow
  bit  9    : Battery 1=Low
  bits 12-13: Mode    0b10=Max, 0b01=Min, 0b00=Normal
  bit  15   : Hold    1=Hold
  bit  23   : Battery 1=Low  (either bit 9 or 23 triggers low-battery)
"""
import pytest

from custom_components.ut353bt.protocol import (
    ACK_PACKET,
    CMD_FAST,
    CMD_HOLD,
    CMD_MAX,
    CMD_MIN,
    CMD_QUERY,
    CMD_SLOW,
    Mode,
    Speed,
    SoundReading,
    is_ack,
    make_cmd,
    parse_packet,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def pkt(hex_str: str) -> bytearray:
    """Convert a compact hex string to a bytearray."""
    return bytearray(bytes.fromhex(hex_str.replace(" ", "")))


# ── Known-good packets from data_captured.txt ─────────────────────────────────
# Each entry: (hex_packet, sound_dba, speed, mode, hold, low_battery)
KNOWN_PACKETS = [
    # label                  hex                                       dBA    speed        mode         hold   batt_low
    ("Slow Max",       "aabb10013b202035342e376442413d3308041e",  54.7, Speed.SLOW, Mode.MAX,    False, False),
    ("Fast Max",       "aabb10013b202035322e306442413d34080416",  52.0, Speed.FAST, Mode.MAX,    False, False),
    ("Slow Min",       "aabb10013b202033382e306442413d33040415",  38.0, Speed.SLOW, Mode.MIN,    False, False),
    ("Slow Normal",    "aabb10013b202035322e386442413d33000415",  52.8, Speed.SLOW, Mode.NORMAL, False, False),
    ("Fast Normal",    "aabb10013b202033362e396442413d34000419",  36.9, Speed.FAST, Mode.NORMAL, False, False),
    ("Fast Min",       "aabb10013b202033362e346442413d34040418",  36.4, Speed.FAST, Mode.MIN,    False, False),
    ("Slow Normal Hold",      "aabb10013b202034382e336442413d33010416",  48.3, Speed.SLOW, Mode.NORMAL, True,  False),
    ("Fast Normal Hold",      "aabb10013b202034382e396442413d3401041d",  48.9, Speed.FAST, Mode.NORMAL, True,  False),
    ("Fast Normal Low",       "aabb10013b202034342e396442413d34400458",  44.9, Speed.FAST, Mode.NORMAL, False, True),
    ("Fast Normal Low Hold",  "aabb10013b202035382e396442413d3441045e",  58.9, Speed.FAST, Mode.NORMAL, True,  True),
    ("Fast Max Low Hold",     "aabb10013b202035342e306442413d34490459",  54.0, Speed.FAST, Mode.MAX,    True,  True),
    ("Fast Max Low",          "aabb10013b202036322e386442413d3448045f",  62.8, Speed.FAST, Mode.MAX,    False, True),
    ("Fast Min Low",          "aabb10013b202034342e376442413d3444045a",  44.7, Speed.FAST, Mode.MIN,    False, True),
    ("Fast Min Low Hold",     "aabb10013b202034342e336442413d34450457",  44.3, Speed.FAST, Mode.MIN,    True,  True),
]


# ── parse_packet ───────────────────────────────────────────────────────────────

class TestParsePacket:

    @pytest.mark.parametrize(
        "label,hex_pkt,dba,speed,mode,hold,low_batt", KNOWN_PACKETS
    )
    def test_known_packets(self, label, hex_pkt, dba, speed, mode, hold, low_batt):
        result = parse_packet(pkt(hex_pkt))
        assert result is not None, f"{label}: parse_packet returned None"
        assert result.sound_dba   == pytest.approx(dba, abs=0.05), f"{label}: sound"
        assert result.speed       == speed,     f"{label}: speed"
        assert result.mode        == mode,      f"{label}: mode"
        assert result.hold        == hold,      f"{label}: hold"
        assert result.low_battery == low_batt,  f"{label}: low_battery"
        assert result.unit        == "dBA"

    def test_returns_none_for_wrong_length_short(self):
        assert parse_packet(bytearray(18)) is None

    def test_parses_overlong_packet_using_first_19_bytes(self):
        # The device sometimes sends 26-byte packets on first subscribe.
        # Extra trailing bytes should be ignored as long as the first 19 are valid.
        base = pkt("aabb10013b202033362e396442413d34000419")
        long_pkt = bytearray(base) + bytearray(7)
        result = parse_packet(long_pkt)
        assert result is not None
        assert abs(result.sound_dba - 36.9) < 0.01

    def test_returns_none_for_overlong_packet_bad_header(self):
        assert parse_packet(bytearray(26)) is None  # all zeros → bad header

    def test_returns_none_for_empty(self):
        assert parse_packet(bytearray()) is None

    def test_returns_none_for_wrong_header(self):
        data = pkt("aabb10013b202033362e396442413d34000419")
        data[0] = 0x00  # corrupt first header byte
        assert parse_packet(data) is None

    def test_returns_none_for_bad_ascii_value(self):
        data = pkt("aabb10013b202033362e396442413d34000419")
        data[6:11] = b"\xFF\xFF\xFF\xFF\xFF"  # non-ASCII sound field
        assert parse_packet(data) is None

    def test_returns_none_for_non_numeric_value(self):
        data = pkt("aabb10013b202033362e396442413d34000419")
        data[6:11] = b"xx.xx"  # valid ASCII but not a float
        assert parse_packet(data) is None

    def test_accepts_bytearray_and_bytes(self):
        hex_str = "aabb10013b202033362e396442413d34000419"
        assert parse_packet(bytearray(bytes.fromhex(hex_str))) is not None
        assert parse_packet(bytes.fromhex(hex_str)) is not None

    def test_status_word_stored(self):
        result = parse_packet(pkt("aabb10013b202033362e396442413d34000419"))
        assert result is not None
        assert result.status_word == 0x34000419

    def test_sound_reading_is_immutable(self):
        result = parse_packet(pkt("aabb10013b202033362e396442413d34000419"))
        assert result is not None
        with pytest.raises((AttributeError, TypeError)):
            result.sound_dba = 0.0  # type: ignore[misc]

    def test_str_representation(self):
        result = parse_packet(pkt("aabb10013b202033362e396442413d34000419"))
        assert result is not None
        s = str(result)
        assert "36.9" in s
        assert "dBA"  in s
        assert "Fast" in s
        assert "Normal" in s
        assert "live" in s
        assert "OK" in s

    def test_str_shows_hold_and_low_battery(self):
        result = parse_packet(pkt("aabb10013b202034342e396442413d34400458"))
        assert result is not None
        assert "LOW" in str(result)

        result_hold = parse_packet(pkt("aabb10013b202034382e396442413d3401041d"))
        assert result_hold is not None
        assert "HOLD" in str(result_hold)


# ── make_cmd ───────────────────────────────────────────────────────────────────

class TestMakeCmd:

    def test_cmd_slow_checksum(self):
        # Verified against PacketLogger capture: AABB 0430 4401 DD
        assert CMD_SLOW == bytes.fromhex("aabb04304401dd")

    def test_cmd_fast_checksum(self):
        # Verified: AABB 0430 4301 DC
        assert CMD_FAST == bytes.fromhex("aabb04304301dc")

    def test_cmd_max_checksum(self):
        # Verified: AABB 0430 3F01 D8
        assert CMD_MAX == bytes.fromhex("aabb04303f01d8")

    def test_cmd_min_checksum(self):
        # Verified: AABB 0430 4001 D9
        assert CMD_MIN == bytes.fromhex("aabb04304001d9")

    def test_cmd_hold_checksum(self):
        # Verified: AABB 0430 4201 DB
        assert CMD_HOLD == bytes.fromhex("aabb04304201db")

    def test_make_cmd_length_is_always_7(self):
        for byte_val in range(0x00, 0x100):
            assert len(make_cmd(byte_val)) == 7

    def test_make_cmd_header_bytes(self):
        cmd = make_cmd(0x42)
        assert cmd[0] == 0xAA
        assert cmd[1] == 0xBB
        assert cmd[2] == 0x04
        assert cmd[3] == 0x30
        assert cmd[5] == 0x01

    def test_make_cmd_checksum_wraps_at_256(self):
        # Choose a cmd_byte that makes the sum exceed 255 to test wrapping.
        cmd = make_cmd(0xFF)
        raw_sum = 0xAA + 0xBB + 0x04 + 0x30 + 0xFF + 0x01 - 1
        assert cmd[6] == raw_sum & 0xFF

    def test_cmd_query_is_single_byte(self):
        assert CMD_QUERY == bytes([0x5E])


# ── is_ack ─────────────────────────────────────────────────────────────────────

class TestIsAck:

    def test_recognises_ack_packet(self):
        assert is_ack(ACK_PACKET) is True

    def test_recognises_ack_bytearray(self):
        assert is_ack(bytearray(ACK_PACKET)) is True

    def test_rejects_query_response(self):
        assert is_ack(pkt("aabb10013b202033362e396442413d34000419")) is False

    def test_rejects_empty(self):
        assert is_ack(b"") is False

    def test_rejects_partial_ack(self):
        assert is_ack(ACK_PACKET[:-1]) is False

    def test_rejects_corrupted_ack(self):
        bad = bytearray(ACK_PACKET)
        bad[2] = 0x00
        assert is_ack(bad) is False
