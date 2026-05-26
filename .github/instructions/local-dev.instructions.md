---
description: "Use when running tests, deploying to Home Assistant, pulling HA logs, or investigating BLE connection issues. Contains local environment details for this dev setup."
---

# Local Development — Knowledge Map

This file is the **agent's source of truth** for the local dev environment.
**Keep it updated** whenever any of the following changes:
- HA host/paths change → update `scripts/deploy.env` (and note it here)
- Conda env name changes → update "Running tests"
- New recurring failure patterns → add to "Known failure patterns"
- A new command is added to `scripts/tasks.sh` → document it here

Human-facing general documentation lives in `DEVELOPMENT.md`.
This file is for agent-specific, local-specific, operational knowledge.

---

## Task Runner

All common tasks go through `scripts/tasks.sh`:

```bash
./scripts/tasks.sh deploy        # rsync component to HA
./scripts/tasks.sh test          # run unit tests
./scripts/tasks.sh logs          # pull connection events from HA log
./scripts/tasks.sh logs --all    # all ut353bt lines (verbose)
./scripts/tasks.sh watch         # live-tail filtered (use during active investigation)
./scripts/tasks.sh watch --all   # live-tail all ut353bt lines
```

---

## Running Tests

Conda environment: **`ha-ut353bt`** (defined in `environment_ha.yml`)

```bash
./scripts/tasks.sh test          # all unit tests (no hardware required)
./scripts/tasks.sh test -v       # verbose

# Live hardware tests (meter must be powered on — not via tasks.sh)
conda run -n ha-ut353bt python -m pytest -m live --live -v
```

---

## Deployment

Config: `scripts/deploy.env` (gitignored) — copy from `scripts/deploy.env.example`.
Variables: `HA_HOST`, `HA_TARGET`.

```bash
cp scripts/deploy.env.example scripts/deploy.env
# fill in HA_HOST and HA_TARGET, then:
./scripts/tasks.sh deploy
```

After deploying, restart Home Assistant to pick up the changes.

---

## Pulling HA Logs

```bash
./scripts/tasks.sh logs          # non-routine connection events (WARNING/ERROR/connect/disconnect)
./scripts/tasks.sh logs --all    # all ut353bt lines except high-volume noise
./scripts/tasks.sh watch         # live-tail filtered (best during active investigation)
./scripts/tasks.sh watch --all   # live-tail all ut353bt lines
```

For raw time-windowed extracts, SSH directly and save to `tmp/` (gitignored):

```bash
ssh "$HA_HOST" "grep '<timestamp prefix>' <config>/home-assistant.log" > tmp/event.log
```

---

## Known Failure Patterns

### BlueZ GATT UnknownObject / WriteValue error
- **Symptom**: `[org.freedesktop.DBus.Error.UnknownObject] Method "WriteValue"... doesn't exist`
- **Cause**: BlueZ tears down GATT objects internally but delays firing the disconnect callback by ~4s. During that window `is_connected` is still `True` but writes fail.
- **Fix applied** (`ha_client.py`): `poll()` now catches `BleakDBusError`/`BleakError`, sets `self._client = None`, and reconnects immediately — collapsing the failure window into a single reconnect.

### Post-reconnect query timeout (startup / device restart)
- **Symptom**: `First CMD_QUERY timed out → reconnecting` then `Poll timed out — device unreachable`; sensors show Unavailable for one poll cycle
- **Cause**: After a wake-up reconnect the device is connected and subscribed, but can take >3s to start responding — especially if the device also disconnected *during* the reconnect attempt (BlueZ retries internally, adding latency).
- **Fix applied** (`ha_client.py`): After any reconnect, `_query_after_reconnect()` retries up to 3 times with 1s between attempts instead of giving up after one try.
- **Symptom**: `establish_connection took 27s` (vs normal ~5s)
- **Cause**: First reconnect attempt via `hci0` with RSSI=-127 (out of range); `bleak_retry_connector` retried via a BT proxy on attempt 2.
- **Not a bug** — `bleak_retry_connector` handled it. Ensure proxy coverage if this recurs.
