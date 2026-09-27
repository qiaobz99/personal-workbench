#!/usr/bin/env bash
# Local KB Workbench — macOS / Linux start script
set -e
cd "$(dirname "$0")"
echo "Local KB Workbench starting ..."
echo "Open your browser at: http://localhost:8080"
echo "(Press Ctrl+C to stop)"
python3 backend/app.py
