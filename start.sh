#!/usr/bin/env bash
# KB Workbench — macOS / Linux start script
set -e
cd "$(dirname "$0")"
PORT="${KB_PORT:-17321}"
# Vault 已迁至 E:\4个人知识库\vault（2026-10-17）
export KB_VAULT="${KB_VAULT:-E:/4个人知识库/vault}"
echo "KB Workbench starting ..."
echo "Open your browser at: http://localhost:${PORT}"
echo "(Override the port with KB_PORT=9001 ./start.sh)"
echo "(Press Ctrl+C to stop)"
python3 backend/app.py
