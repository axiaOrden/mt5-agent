#!/usr/bin/env bash
# Stop the Wine MT5 bridge started by start-mt5-bridge.sh.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f logs/bridge.pid ]]; then
    echo "No bridge pid file found (logs/bridge.pid). Nothing to stop."
    exit 0
fi

pid="$(cat logs/bridge.pid)"

if ! kill -0 "$pid" 2>/dev/null; then
    echo "Bridge process $pid is not running. Removing stale pid file."
    rm -f logs/bridge.pid
    exit 0
fi

echo "Stopping MT5 bridge (pid $pid) ..."
kill "$pid"
for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
        break
    fi
    sleep 0.25
done

if kill -0 "$pid" 2>/dev/null; then
    echo "Bridge did not exit gracefully; forcing."
    kill -9 "$pid" || true
fi

rm -f logs/bridge.pid
echo "Bridge stopped."
