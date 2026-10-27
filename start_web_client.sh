#!/bin/bash
# -------------------------------------------------------------
# Launch script for Client Web Server (Linux / macOS / Pi)
# -------------------------------------------------------------

cd "$(dirname "$0")" || exit 1

echo "======================================================="
echo "   Starting Vosk Pi Voice Client Web Server"
echo "======================================================="
echo ""
echo "Options:"
echo "  1. Start HTTP Server (Default, port 8080)"
echo "  2. Start HTTPS Server (Self-signed SSL, port 8443 - Recommended for Mobile)"
echo "  3. Start Mock Mode (Test UI without physical Pi)"
echo ""

if [ "$#" -gt 0 ]; then
    python3 clients/client_web_server.py "$@"
    exit 0
fi

read -rp "Select mode [1/2/3, default: 1]: " choice
choice="${choice:-1}"

if [ "$choice" = "3" ]; then
    echo "Starting in Mock Mode on port 8080..."
    python3 clients/client_web_server.py --mock-pi
    exit 0
fi

read -rp "Enter Pi IP or hostname [default: raspberrypi.local]: " pi_ip
pi_ip="${pi_ip:-raspberrypi.local}"

if [[ "$pi_ip" != http* ]]; then
    pi_ip="http://${pi_ip}:8765"
fi

if [ "$choice" = "2" ]; then
    echo "Starting with SSL on port 8443 for Pi at ${pi_ip}..."
    python3 clients/client_web_server.py --pi "$pi_ip" --ssl
else
    echo "Starting HTTP server on port 8080 for Pi at ${pi_ip}..."
    python3 clients/client_web_server.py --pi "$pi_ip"
fi
