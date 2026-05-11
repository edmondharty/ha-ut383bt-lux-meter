"""Constants for the Uni-T UT353BT integration."""

DOMAIN = "ut353bt"

# BLE GATT characteristic UUIDs (service 0000ff12-...)
DATA_IN_UUID  = "0000ff01-0000-1000-8000-00805f9b34fb"  # Write-without-response
DATA_OUT_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"  # Notify

# Config / options keys
CONF_POLL_INTERVAL = "poll_interval"

# Defaults
DEFAULT_POLL_INTERVAL = 5  # seconds
MIN_POLL_INTERVAL     = 1   # seconds
MAX_POLL_INTERVAL     = 300 # seconds

DEFAULT_POLL_TIMEOUT  = 3.0  # seconds — time to wait for a BLE response

# Entity unique-ID suffixes
SUFFIX_SOUND             = "sound"
SUFFIX_BATTERY           = "battery"
SUFFIX_MODE              = "mode"
SUFFIX_SPEED             = "speed"
SUFFIX_HOLD              = "hold"
SUFFIX_CONNECTION_STATUS = "connection_status"
SUFFIX_RSSI              = "rssi"
SUFFIX_LAST_SEEN         = "last_seen"

# Connection status values (used by the diagnostic sensor)
CONN_STATUS_CONNECTED    = "Connected"
CONN_STATUS_CONNECTING   = "Connecting"
CONN_STATUS_DISCONNECTED = "Disconnected"
