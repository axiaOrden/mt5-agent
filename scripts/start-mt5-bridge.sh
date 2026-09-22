#!/usr/bin/env bash
# Start the read-only MT5 bridge under Wine.
# Reads .env, sets WINEPREFIX, launches the bridge with Windows Python.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
    echo "ERROR: .env not found. Copy .env.example to .env first." >&2
    exit 1
fi

# Load .env without interpreting backslashes (Windows paths).
while IFS='=' read -r key value; do
    case "$key" in
        ''|\#*) continue ;;
    esac
    export "$key=$value"
done < .env

WINE_BINARY="${WINE_BINARY:-/usr/bin/wine}"
WINE_PREFIX="${WINE_PREFIX:-/home/heaxia/.wine}"
WINE_PYTHON="${WINE_PYTHON:-}"
MT5_TERMINAL_WINDOWS="${MT5_TERMINAL_WINDOWS:-}"
MT5_BRIDGE_HOST="${MT5_BRIDGE_HOST:-127.0.0.1}"
MT5_BRIDGE_PORT="${MT5_BRIDGE_PORT:-8765}"

if [[ -z "$WINE_PYTHON" ]]; then
    echo "ERROR: WINE_PYTHON is not set in .env" >&2
    exit 1
fi
if [[ -z "$MT5_TERMINAL_WINDOWS" ]]; then
    echo "ERROR: MT5_TERMINAL_WINDOWS is not set in .env" >&2
    exit 1
fi

export WINEPREFIX="$WINE_PREFIX"
export MT5_TERMINAL_WINDOWS
export MT5_BRIDGE_HOST
export MT5_BRIDGE_PORT

mkdir -p logs

if [[ -f logs/bridge.pid ]] && kill -0 "$(cat logs/bridge.pid)" 2>/dev/null; then
    echo "Bridge already running (pid $(cat logs/bridge.pid))."
    exit 0
fi

echo "Starting MT5 bridge on ${MT5_BRIDGE_HOST}:${MT5_BRIDGE_PORT} ..."
nohup "$WINE_BINARY" "$WINE_PYTHON" bridge/mt5_bridge.py >> logs/bridge.log 2>&1 &
echo $! > logs/bridge.pid

echo "Bridge pid $(cat logs/bridge.pid). Log: logs/bridge.log"
echo "Health check: ./scripts/check-mt5-bridge.sh"
