#!/bin/bash
# -------------------------------------------------------------
# Launch script for Raspberry Pi Voice Detection Server
# -------------------------------------------------------------
# Automatically locates the Vosk model wherever the repo is cloned!

cd "$(dirname "$0")" || exit 1

echo "======================================================="
echo "   Starting Raspberry Pi Voice Detection Server"
echo "======================================================="

python3 servers/voice_detection_server.py "$@"
