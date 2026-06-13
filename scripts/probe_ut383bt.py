"""Standalone live probe for the UT383BT — no Home Assistant required.

Connects directly with bleak (the same BLE library HA uses), reads the
Device Information Service characteristics (manufacturer/model/serial/firmware),
then drives one live lux reading by writing the 0x5E poll command and parsing
the notification with the integration's own protocol parser.

Usage:
    python scripts/probe_ut383bt.py [ADDRESS]

ADDRESS defaults to the meter seen in the btsnoop capture. The meter must be
powered on and within Bluetooth range of this PC.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from bleak import BleakClient, BleakScanner

# Load the integration's pure protocol module without importing the HA package.
_proto_path = Path(__file__).resolve().parent.parent / "custom_components" / "ut383bt" / "protocol.py"
_spec = importlib.util.spec_from_file_location("ut383bt_protocol", _proto_path)
protocol = importlib.util.module_from_spec(_spec)
sys.modules["ut383bt_protocol"] = protocol
_spec.loader.exec_module(protocol)

DEFAULT_ADDRESS = "18:90:67:FE:A7:79"

DATA_IN_UUID  = "0000ff01-0000-1000-8000-00805f9b34fb"
DATA_OUT_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"

DIS_CHARS = {
    "Manufacturer": "00002a29-0000-1000-8000-00805f9b34fb",
    "Model":        "00002a24-0000-1000-8000-00805f9b34fb",
    "Serial":       "00002a25-0000-1000-8000-00805f9b34fb",
    "Firmware":     "00002a26-0000-1000-8000-00805f9b34fb",
    "Hardware":     "00002a27-0000-1000-8000-00805f9b34fb",
    "Software":     "00002a28-0000-1000-8000-00805f9b34fb",
}


async def main(address: str) -> int:
    print(f"Scanning for {address} (10s)...")
    device = await BleakScanner.find_device_by_address(address, timeout=10.0)
    if device is None:
        print("  NOT FOUND — make sure the meter is powered on, Bluetooth enabled, near this PC.")
        return 1
    print(f"  Found: {device.name} ({device.address})")

    async with BleakClient(device) as client:
        print(f"Connected: {client.is_connected}\n")

        print("Device Information Service:")
        for label, uuid in DIS_CHARS.items():
            try:
                raw = await client.read_gatt_char(uuid)
                text = bytes(raw).decode("ascii", errors="replace").strip("\x00").strip()
                print(f"  {label:<12}: {text!r}  (raw {bytes(raw).hex()})")
            except Exception as err:  # noqa: BLE001
                print(f"  {label:<12}: <unreadable: {err}>")

        print("\nLive reading (subscribe ff02, poll 0x5E):")
        got: list = []

        def on_notify(_sender, data: bytearray) -> None:
            got.append(bytes(data))

        await client.start_notify(DATA_OUT_UUID, on_notify)
        await asyncio.sleep(0.3)
        for _ in range(5):
            await client.write_gatt_char(DATA_IN_UUID, protocol.CMD_QUERY, response=False)
            await asyncio.sleep(0.4)
            if got:
                break
        await client.stop_notify(DATA_OUT_UUID)

        if not got:
            print("  No notification received.")
            return 1
        raw = got[-1]
        reading = protocol.parse_packet(raw)
        print(f"  raw notification: {raw.hex()}")
        print(f"  parsed          : {reading}")
        return 0


if __name__ == "__main__":
    addr = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    raise SystemExit(asyncio.run(main(addr)))
