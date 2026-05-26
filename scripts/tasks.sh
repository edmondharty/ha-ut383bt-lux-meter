#!/usr/bin/env bash
# Unified task runner for the ut353bt HA integration.
#
# Usage:
#   ./scripts/tasks.sh deploy        — rsync component to Home Assistant
#   ./scripts/tasks.sh test          — run unit tests (no hardware required)
#   ./scripts/tasks.sh logs          — pull non-routine connection events from HA log
#   ./scripts/tasks.sh watch         — live-tail HA log (Ctrl-C to stop)
#
# Configuration (required for deploy/logs/watch):
#   Copy scripts/deploy.env.example to scripts/deploy.env and fill in your values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${SCRIPT_DIR}/deploy.env"
CONDA_ENV="ha-ut353bt"

# Patterns that indicate a meaningful connection event (used by logs + watch).
# Deliberately excludes noisy success lines matched by broad terms like "Poll".
_SIGNAL_PATTERN='WARNING|ERROR|CRITICAL|disconnected unexpectedly|Not connected|timed out|Connecting to|establish_connection took|Connected and subscribed|GATT error|Post-'
_NOISE_PATTERN='Finished fetching|Manually updated|success: True|Fetching ut353bt'

# ── Helpers ────────────────────────────────────────────────────────────────────

load_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: ${ENV_FILE} not found."
    echo "Copy scripts/deploy.env.example to scripts/deploy.env and fill in your values."
    exit 1
  fi
  # shellcheck source=deploy.env
  source "$ENV_FILE"
  : "${HA_HOST:?HA_HOST must be set in deploy.env}"
  : "${HA_TARGET:?HA_TARGET must be set in deploy.env}"
}

ha_log_dir() {
  # HA_TARGET ends at the component dir; config root is two levels up.
  dirname "$(dirname "$HA_TARGET")"
}

# ── Commands ───────────────────────────────────────────────────────────────────

cmd_deploy() {
  load_env
  local src="${REPO_ROOT}/custom_components/ut353bt/"
  echo "Deploying to ${HA_HOST}:${HA_TARGET} ..."
  if ! rsync -av --delete --exclude='__pycache__' --exclude='*.pyc' "$src" "${HA_HOST}:${HA_TARGET}/"; then
    echo ""
    echo "Deploy failed. If the error was 'permission denied', fix ownership on the HA host:"
    echo "  ssh ${HA_HOST} 'sudo chown -R \$USER ${HA_TARGET}'"
    exit 1
  fi
  echo "Done. Restart Home Assistant to apply the changes."
}

cmd_test() {
  echo "Running unit tests in conda env '${CONDA_ENV}' ..."
  conda run -n "$CONDA_ENV" python -m pytest "${REPO_ROOT}/tests/" -x -q "$@"
}

cmd_logs() {
  load_env
  local log_dir; log_dir="$(ha_log_dir)"
  local log_current="${log_dir}/home-assistant.log"
  local log_prev="${log_dir}/home-assistant.log.1"

  echo "Connection events from ${HA_HOST} ..."
  # shellcheck disable=SC2029
  ssh "$HA_HOST" "
    for f in '${log_prev}' '${log_current}'; do
      [ -f \"\$f\" ] && grep 'custom_components\.ut353bt' \"\$f\" \
        | grep -E '${_SIGNAL_PATTERN}' \
        | grep -v '${_NOISE_PATTERN}' \
        || true
    done
  "
}

cmd_watch() {
  load_env
  local log_dir; log_dir="$(ha_log_dir)"
  local log_current="${log_dir}/home-assistant.log"

  echo "Watching ${HA_HOST}:${log_current} (Ctrl-C to stop) ..."
  # shellcheck disable=SC2029
  ssh "$HA_HOST" "tail -F '${log_current}'" \
    | grep --line-buffered 'custom_components\.ut353bt' \
    | grep --line-buffered -v "${_NOISE_PATTERN}"
}

# ── Dispatch ───────────────────────────────────────────────────────────────────

usage() {
  echo "Usage: $(basename "$0") <command> [args]"
  echo ""
  echo "Commands:"
  echo "  deploy   Rsync component to Home Assistant (requires deploy.env)"
  echo "  test     Run unit tests via conda env '${CONDA_ENV}'"
  echo "  logs     Pull non-routine connection events from HA log (requires deploy.env)"
  echo "  watch    Live-tail HA log — all ut353bt lines except noise (requires deploy.env)"
  exit 1
}

case "${1:-}" in
  deploy) shift; cmd_deploy "$@" ;;
  test)   shift; cmd_test   "$@" ;;
  logs)   shift; cmd_logs   "$@" ;;
  watch)  shift; cmd_watch  "$@" ;;
  *)      usage ;;
esac
