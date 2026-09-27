#!/usr/bin/env bash
# Local KB Workbench — macOS / Linux start script
set -e
cd "$(dirname "$0")"
PORT="${KB_PORT:-17321}"
echo "Local KB Workbench starting ..."
echo "Open your browser at: http://localhost:${PORT}"
echo "(Override the port with KB_PORT=9001 ./start.sh)"
echo "(Press Ctrl+C to stop)"
python3 backend/app.py
