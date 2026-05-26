# Development

This document is for contributors and developers. For user installation instructions see [README.md](README.md).

---

## Repository layout

| Path | Purpose |
|------|---------|
| `custom_components/ut353bt/` | The HACS component — install this in HA |
| `tests/` | Unit tests (BLE fully mocked — no hardware needed) |
| `tests/test_live_ble.py` | Live hardware tests (opt-in, skipped by default) |
| `scripts/` | Developer task runner (`tasks.sh`) and local config |
| `.github/instructions/` | Agent instructions for local dev environment |
| `.github/workflows/` | CI — runs unit tests on every push / PR |

Key source files in `custom_components/ut353bt/`:
- **`ha_client.py`** — BLE connection lifecycle (connect, poll, reconnect)
- **`coordinator.py`** — HA `DataUpdateCoordinator` wrapper; drives polling
- **`protocol.py`** — pure-Python packet parser and command builder (no HA/BLE deps)

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

## Deploying to a local HA instance

```bash
./scripts/tasks.sh deploy
```

This rsyncs `custom_components/ut353bt/` to your HA host.

First-time setup:
```bash
cp scripts/deploy.env.example scripts/deploy.env
# edit scripts/deploy.env with your HA_HOST and HA_TARGET
```

`scripts/deploy.env` is gitignored — each contributor keeps their own.

---

## Pulling logs from Home Assistant

First, enable debug logging in your HA `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.ut353bt: debug
    bleak_retry_connector: debug
    habluetooth: debug
```

Restart HA after adding this, then pull connection events:

```bash
./scripts/tasks.sh logs
```

Log files on the HA host (default path):
- `<config>/home-assistant.log` (current)
- `<config>/home-assistant.log.1` (previous)

Save raw extracts to `tmp/` (gitignored) for investigation.

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
