"""Constants for the Uni-T UT383BT lux meter integration."""

DOMAIN = "ut383bt"

# BLE GATT characteristic UUIDs (vendor service 0000ff12-...)
DATA_IN_UUID  = "0000ff01-0000-1000-8000-00805f9b34fb"  # Write-without-response (poll command)
DATA_OUT_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"  # Notify (measurement stream)

# Config / options keys
CONF_POLL_INTERVAL = "poll_interval"

# Defaults
DEFAULT_POLL_INTERVAL = 5   # seconds
MIN_POLL_INTERVAL     = 1   # seconds
MAX_POLL_INTERVAL     = 300 # seconds

DEFAULT_POLL_TIMEOUT  = 3.0  # seconds — time to wait for a BLE response

# Entity unique-ID suffixes
SUFFIX_ILLUMINANCE       = "illuminance"
SUFFIX_CONNECTION_STATUS = "connection_status"
SUFFIX_RSSI              = "rssi"
SUFFIX_LAST_SEEN         = "last_seen"

# Connection status values (used by the diagnostic sensor)
CONN_STATUS_CONNECTED    = "Connected"
CONN_STATUS_CONNECTING   = "Connecting"
CONN_STATUS_DISCONNECTED = "Disconnected"
