#!/usr/bin/env bash
# Health-check the Wine MT5 bridge.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
    while IFS='=' read -r key value; do
        case "$key" in
            ''|\#*) continue ;;
        esac
        export "$key=$value"
    done < .env
fi

HOST="${MT5_BRIDGE_HOST:-127.0.0.1}"
PORT="${MT5_BRIDGE_PORT:-8765}"

curl -sS --max-time 5 "http://${HOST}:${PORT}/health" | python3 -m json.tool
