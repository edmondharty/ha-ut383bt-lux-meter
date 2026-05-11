# Development

This document is for contributors and developers. For user installation instructions see [README.md](README.md).

---

## Repository layout

```
custom_components/ut353bt/   # HACS component (install this in HA)
│  __init__.py               # Integration setup / teardown
│  config_flow.py            # UI discovery & options flows
│  coordinator.py            # DataUpdateCoordinator (polling)
│  ha_client.py              # HA-native BLE client (bleak-retry-connector)
│  protocol.py               # Pure-Python packet parser & command builder
│  const.py                  # Constants
│  sensor.py                 # Sound level + diagnostic sensor entities
│  binary_sensor.py          # Battery low binary sensor entity
│  select.py                 # Mode & Speed select entities
│  switch.py                 # Hold switch entity
│  diagnostics.py            # HA diagnostics download support
│  manifest.json             # HACS / HA manifest
│  strings.json              # UI strings
│  translations/en.json      # English translations
tests/
│  test_live_ble.py          # Live BLE hardware tests (skipped by default)
│  ha/
│     conftest.py            # Shared fixtures for HA integration tests
│     test_config_flow.py    # Config & options flow tests
│     test_coordinator.py    # Coordinator tests
│     test_diagnostics.py    # Diagnostics tests
│     test_entities.py       # Entity state & control tests
│     test_ha_client.py      # HA BLE client tests (mocked BLE)
│     test_sensor.py         # Sensor entity tests
│     test_protocol.py       # Protocol parser unit tests (no BLE needed)
.github/workflows/
│  tests.yml                 # CI — runs unit tests on every push / PR
hacs.json                    # HACS metadata
environment_ha.yml           # Conda environment for HA integration tests
```

---

## Setting up the test environment

Requires [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or Anaconda.

```bash
# Create and activate the conda environment
conda env create -f environment_ha.yml
conda activate ha-ut353bt

# Run all unit tests (no hardware required — BLE is fully mocked)
pytest tests/ --ignore=tests/test_live_ble.py -v

# Run only the HA integration tests
pytest tests/ha/ -v
```

The CI workflow (`.github/workflows/tests.yml`) runs the same command on every
push and pull request, on both Python 3.12 and 3.13.

---

## Live hardware tests

`tests/test_live_ble.py` connects directly to the physical meter via the system
Bluetooth stack. These tests are excluded from normal runs and CI — opt in explicitly:

```bash
conda activate ha-ut353bt

# Requires the meter to be powered on and Bluetooth enabled
pytest -m live --live -v
```

The suite scans for a device named `UT353BT` (12 s timeout), skips automatically
if the meter is not found, and covers: device discovery, polling a valid reading,
Fast/Slow speed switching, hold toggle, and a full Normal → Max → Min → Normal
mode cycle.

On macOS you may be prompted for Bluetooth permission — grant it under
**System Settings → Privacy & Security → Bluetooth**.

---

## Installing in a local HA development instance

```bash
# Symlink the component into your HA config directory (no copy needed)
ln -s $(pwd)/custom_components/ut353bt \
      /path/to/ha-config/custom_components/ut353bt
```

Restart HA and the integration will be available for testing.

---

## Protocol notes

The UT353BT communicates over BLE GATT:

| UUID | Role |
|---|---|
| `0000ff01-0000-1000-8000-00805f9b34fb` | **Write** — send query / control commands |
| `0000ff02-0000-1000-8000-00805f9b34fb` | **Notify** — receive 26-byte measurement packets |

The protocol was reverse-engineered from PacketLogger captures (no official documentation).
See [`custom_components/ut353bt/protocol.py`](custom_components/ut353bt/protocol.py) for the
full packet layout and command byte definitions.

### Commands (write to `ff01`)

| Command | Effect |
|---|---|
| `0x01` | Query — request a measurement |
| `0x02` | Hold toggle — freeze / unfreeze the display |
| `0x05` | Max mode — enter peak-hold mode |
| `0x06` | Min / cycle mode — advance Max → Min → Normal |
| `0x07` | Fast response |
| `0x08` | Slow response |

### Packet format (notify on `ff02`, 26 bytes on BlueZ)

Bytes 0–18 carry the measurement. Key fields:

| Byte(s) | Content |
|---|---|
| 2–3 | Sound level × 10 (big-endian), e.g. `0x02 0x29` = 55.3 dBA |
| 4 | Status flags: bit 0 = hold, bit 3 = low battery, bits 4–5 = mode, bit 6 = speed |
