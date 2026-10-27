"""Client Web Server and LAN Reverse Proxy for the Vosk Voice Controller.

Features:
- Serves the responsive web application to phones, tablets, and laptops on the local Wi-Fi.
- Automatically proxies API requests to the Raspberry Pi voice detection server, eliminating CORS and Mixed-Content blocks.
- Pure direct GPIO signals for quick action buttons (/api/control), bypassing speech recognition.
- Hardware diagnostics and individual pin controls (/api/gpio) for Green LED, Relay, Yellow LED, Red LED.
- Shared multi-device activity feed (/api/history).
- Dynamic LAN IP detection and self-signed SSL certificate generation for mobile microphone access.
- Mock Mode (--mock-pi) for development and UI testing without a physical Raspberry Pi.
"""

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Root and client directories
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WEB_DIR = PROJECT_ROOT / "clients" / "web"
AUDIO_DIR = PROJECT_ROOT / "audio"
DEFAULT_CERTS_DIR = PROJECT_ROOT / "certs"


def get_local_ip_addresses() -> list[str]:
    """Return all non-loopback IPv4 addresses for this machine."""
    ips = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass

    return sorted(list(ips))


def ensure_ssl_certificates(cert_path: Path, key_path: Path) -> bool:
    """Generate a self-signed SSL certificate if one does not already exist."""
    if cert_path.exists() and key_path.exists():
        return True

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    openssl_bin = shutil.which("openssl")
    if openssl_bin:
        cmd = [
            openssl_bin,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "365",
            "-nodes",
            "-subj",
            "/CN=vosk-voice-controller",
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (subprocess.SubprocessError, OSError):
            pass

    return False


class MockPiState:
    """Simulated Raspberry Pi hardware state for testing without physical hardware."""

    def __init__(self) -> None:
        self.light_on = False
        self.relay_on = False
        self.yellow_led_on = False
        self.red_led_on = False
        self.last_transcript = ""
        self.last_command = "OFF"
        self.message = "System ready (Mock Mode)"
        self.history: list[dict] = []

    def add_history(
        self,
        client_ip: str,
        action_type: str,
        transcript: str,
        command: str,
        message: str,
    ) -> dict:
        entry = {
            "id": f"{int(time.time() * 1000)}",
            "time": datetime.now().strftime("%H:%M:%S"),
            "client_ip": client_ip or "Local Device",
            "type": action_type,
            "transcript": transcript,
            "command": command,
            "message": message,
        }
        self.history.insert(0, entry)
        if len(self.history) > 60:
            self.history.pop()
        return entry

    def get_status(self) -> dict:
        return {
            "transcript": self.last_transcript,
            "command": self.last_command,
            "light_on": self.light_on,
            "relay_on": self.relay_on,
            "yellow_led_on": self.yellow_led_on,
            "status_led_on": self.yellow_led_on,
            "red_led_on": self.red_led_on,
            "message": self.message,
            "mock": True,
        }

    def process_command(
        self, transcript: str, command: str, client_ip: str = "Unknown"
    ) -> dict:
        self.last_transcript = transcript
        self.last_command = command
        if command == "ON":
            self.light_on = True
            self.relay_on = True
            self.yellow_led_on = False
            self.red_led_on = False
            self.message = "Light turned on (simulated)"
        elif command == "OFF":
            self.light_on = False
            self.relay_on = False
            self.yellow_led_on = False
            self.red_led_on = False
            self.message = "Light turned off (simulated)"
        else:
            self.yellow_led_on = True
            self.red_led_on = False
            self.message = "No supported light command recognized (simulated)"

        self.add_history(client_ip, "VOICE", transcript, command, self.message)
        return self.get_status()

    def set_direct(self, command: str, client_ip: str = "Unknown") -> dict:
        cmd = command.upper()
        if cmd == "ON":
            self.light_on = True
            self.relay_on = True
            self.yellow_led_on = False
            self.red_led_on = False
            self.message = "Light turned on (pure GPIO signal)"
        elif cmd == "OFF":
            self.light_on = False
            self.relay_on = False
            self.yellow_led_on = False
            self.red_led_on = False
            self.message = "Light turned off (pure GPIO signal)"
        else:
            self.message = f"Unknown direct command: {command}"

        self.last_transcript = f"Pure Signal: {cmd}"
        self.last_command = cmd
        self.add_history(
            client_ip, "DIRECT_GPIO", f"Pure Signal: Light {cmd}", cmd, self.message
        )
        return self.get_status()

    def set_pin(
        self, component: str, state: bool, client_ip: str = "Unknown"
    ) -> dict:
        comp = component.lower().strip()
        state_str = "ON" if state else "OFF"

        if comp in ("green", "light"):
            self.light_on = state
            name = "Green LED"
        elif comp == "relay":
            self.relay_on = state
            name = "12V Relay"
        elif comp in ("yellow", "status"):
            self.yellow_led_on = state
            name = "Yellow LED"
        elif comp in ("red", "error"):
            self.red_led_on = state
            name = "Red Error LED"
        elif comp == "all":
            self.light_on = state
            self.relay_on = state
            self.yellow_led_on = state
            self.red_led_on = state
            name = "All Hardware Pins"
        else:
            name = component

        self.message = f"{name} set to {state_str} (simulated)"
        self.last_transcript = f"Test Pin: {name}"
        self.last_command = state_str
        self.add_history(
            client_ip, "PIN_TEST", f"Test: {name} {state_str}", state_str, self.message
        )
        return self.get_status()


def create_request_handler(
    target_pi_url: str,
    web_dir: Path,
    mock_mode: bool = False,
):
    current_pi_url = [target_pi_url.rstrip("/")]
    mock_state = MockPiState() if mock_mode else None
    server_history: list[dict] = []

    def record_history(client_ip: str, action_type: str, transcript: str, command: str, message: str):
        entry = {
            "id": f"{int(time.time() * 1000)}",
            "time": datetime.now().strftime("%H:%M:%S"),
            "client_ip": client_ip or "Local Device",
            "type": action_type,
            "transcript": transcript,
            "command": command,
            "message": message,
        }
        server_history.insert(0, entry)
        if len(server_history) > 60:
            server_history.pop()
        return entry

    class WebClientRequestHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_dir), **kwargs)

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS, PUT"
            )
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-Requested-With"
            )

        def _send_json_response(self, data: object, status: int = 200) -> None:
            payload = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(payload)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/api/status":
                self._handle_get_status()
                return
            elif self.path == "/api/config":
                self._handle_get_config()
                return
            elif self.path == "/api/history":
                self._handle_get_history()
                return
            elif self.path == "/api/commands":
                from core.command_parser import get_command_examples
                self._send_json_response(get_command_examples())
                return

            # Default to serving static files from clients/web
            super().do_GET()

        def do_DELETE(self) -> None:
            if self.path == "/api/history":
                server_history.clear()
                if mock_state:
                    mock_state.history.clear()
                self._send_json_response({"success": True, "message": "History cleared"})
                return
            self.send_error(404, "Endpoint not found")

        def do_POST(self) -> None:
            client_ip = self.client_address[0]
            if self.path == "/api/audio":
                self._handle_post_audio(client_ip)
                return
            elif self.path == "/api/control":
                self._handle_post_control(client_ip)
                return
            elif self.path == "/api/gpio":
                self._handle_post_gpio(client_ip)
                return
            elif self.path == "/api/config":
                self._handle_post_config()
                return
            elif self.path == "/api/quick":
                self._handle_post_control(client_ip)
                return

            self.send_error(404, "Endpoint not found")

        def _handle_get_status(self) -> None:
            if mock_state is not None:
                self._send_json_response(mock_state.get_status())
                return

            url = f"{current_pi_url[0]}/status"
            req = urllib.request.Request(url, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    body = response.read()
                    data = json.loads(body.decode("utf-8"))
                    self._send_json_response(data, status=response.status)
            except urllib.error.HTTPError as err:
                self._send_json_response(
                    {"error": f"Pi server error: {err.code}"}, status=err.code
                )
            except (urllib.error.URLError, OSError, TimeoutError) as err:
                self._send_json_response(
                    {
                        "error": f"Could not connect to Pi at {current_pi_url[0]} ({err})",
                        "connected": False,
                    },
                    status=502,
                )

        def _handle_get_history(self) -> None:
            if mock_state is not None:
                self._send_json_response(mock_state.history)
                return

            url = f"{current_pi_url[0]}/history"
            req = urllib.request.Request(url, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=3) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    self._send_json_response(data)
                    return
            except Exception:
                self._send_json_response(server_history)

        def _handle_get_config(self) -> None:
            self._send_json_response(
                {
                    "pi_url": current_pi_url[0],
                    "local_ips": get_local_ip_addresses(),
                    "mock": mock_state is not None,
                }
            )

        def _handle_post_config(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                new_url = body.get("pi_url", "").strip().rstrip("/")
                if new_url and new_url.startswith(("http://", "https://")):
                    current_pi_url[0] = new_url
                    self._send_json_response(
                        {
                            "success": True,
                            "pi_url": current_pi_url[0],
                            "message": f"Target Pi URL updated to {current_pi_url[0]}",
                        }
                    )
                else:
                    self._send_json_response(
                        {"error": "Invalid URL: Must start with http:// or https://"},
                        status=400,
                    )
            except Exception as err:
                self._send_json_response({"error": str(err)}, status=400)

        def _handle_post_control(self, client_ip: str) -> None:
            """Pure direct GPIO signal to turn lights ON or OFF."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                command = body.get("command", "ON").upper()
            except Exception:
                command = "ON"

            if mock_state is not None:
                res = mock_state.set_direct(command, client_ip=client_ip)
                self._send_json_response(res)
                return

            url = f"{current_pi_url[0]}/control"
            payload = json.dumps({"command": command}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=6) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    record_history(
                        client_ip,
                        "DIRECT_GPIO",
                        f"Pure Signal: Light {command}",
                        command,
                        data.get("message", "Light command executed"),
                    )
                    self._send_json_response(data, status=response.status)
            except Exception as err:
                self._send_json_response(
                    {"error": f"Failed to execute direct GPIO command on Pi: {err}"},
                    status=502,
                )

        def _handle_post_gpio(self, client_ip: str) -> None:
            """Individual pin test toggle for Green LED, Relay, Yellow LED, or Red LED."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                component = body.get("component", "green")
                state = bool(body.get("state", False))
            except Exception as err:
                self._send_json_response({"error": f"Invalid GPIO body: {err}"}, status=400)
                return

            if mock_state is not None:
                res = mock_state.set_pin(component, state, client_ip=client_ip)
                self._send_json_response(res)
                return

            url = f"{current_pi_url[0]}/gpio"
            payload = json.dumps({"component": component, "state": state}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=6) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    record_history(
                        client_ip,
                        "PIN_TEST",
                        f"Pin Test: {component} {'ON' if state else 'OFF'}",
                        "TEST",
                        data.get("message", "Pin updated"),
                    )
                    self._send_json_response(data, status=response.status)
            except Exception as err:
                self._send_json_response(
                    {"error": f"Failed to execute GPIO pin test on Pi: {err}"},
                    status=502,
                )

        def _handle_post_audio(self, client_ip: str) -> None:
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0:
                    self._send_json_response(
                        {"error": "Empty audio payload"}, status=400
                    )
                    return
                audio_bytes = self.rfile.read(length)
            except Exception as err:
                self._send_json_response(
                    {"error": f"Failed to read audio: {err}"}, status=400
                )
                return

            if mock_state is not None:
                res = mock_state.process_command(
                    "turn on the light",
                    "ON" if not mock_state.light_on else "OFF",
                    client_ip=client_ip,
                )
                self._send_json_response(res)
                return

            url = f"{current_pi_url[0]}/audio"
            req = urllib.request.Request(
                url,
                data=audio_bytes,
                headers={"Content-Type": "audio/wav"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=12) as response:
                    body = response.read()
                    data = json.loads(body.decode("utf-8"))
                    record_history(
                        client_ip,
                        "VOICE",
                        data.get("transcript", ""),
                        data.get("command", "UNKNOWN"),
                        data.get("message", ""),
                    )
                    self._send_json_response(data, status=response.status)
            except urllib.error.HTTPError as err:
                err_body = err.read().decode("utf-8", errors="replace")
                self._send_json_response(
                    {"error": f"Pi HTTP {err.code}: {err_body}"}, status=err.code
                )
            except (urllib.error.URLError, OSError, TimeoutError) as err:
                self._send_json_response(
                    {
                        "error": f"Could not reach Pi server at {current_pi_url[0]}: {err}"
                    },
                    status=502,
                )

        def log_message(self, format: str, *args) -> None:
            sys.stderr.write(f"[CLIENT WEB SERVER] {format % args}\n")

    return WebClientRequestHandler


def print_banner(
    host: str,
    port: int,
    is_ssl: bool,
    pi_url: str,
    local_ips: list[str],
    mock_mode: bool,
) -> None:
    protocol = "https" if is_ssl else "http"
    line = "=" * 68
    print("\n" + line)
    print("  [*] VOSK PI VOICE CONTROLLER - CLIENT WEB SERVER")
    print(line)
    print(f"  * Local Machine:    {protocol}://localhost:{port}")
    if local_ips:
        for ip in local_ips:
            print(f"  * LAN Network:      {protocol}://{ip}:{port}")
    else:
        print(f"  * LAN Network:      {protocol}://{host}:{port}")
    print(f"  * Target Pi Server: {pi_url}")
    if mock_mode:
        print("  * Mode:             SIMULATED MOCK PI (Physical Pi not required)")
    else:
        print("  * Mode:             LIVE PROXY (Forwarding commands/audio to Pi)")
    print(line)
    print("  Pages Available:")
    print(f"    1. Voice Controller:     {protocol}://localhost:{port}/index.html")
    print(f"    2. Hardware Diagnostics: {protocol}://localhost:{port}/diagnostics.html")
    print(f"    3. Commands & Help:      {protocol}://localhost:{port}/help.html")
    print(line)
    if is_ssl:
        print("  [>] Mobile Devices: Connect via HTTPS and bypass self-signed warning")
        print("      to grant browser microphone permissions over Wi-Fi.")
    else:
        print("  [>] Mobile Notice: Run with --ssl to allow mobile microphone recording.")
    print(line + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Host the client web interface and reverse proxy on the local network."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Interface to bind on (default: 0.0.0.0 for LAN access)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to serve on (default: 8443 if SSL, 8080 if HTTP)",
    )
    parser.add_argument(
        "--pi",
        default="http://raspberrypi.local:8765",
        help="Target Raspberry Pi voice detection server URL (default: http://raspberrypi.local:8765)",
    )
    parser.add_argument(
        "--ssl",
        "--https",
        action="store_true",
        help="Enable HTTPS with self-signed certificate (required for mobile mic access)",
    )
    parser.add_argument(
        "--cert",
        type=str,
        default=None,
        help="Custom SSL certificate path (PEM)",
    )
    parser.add_argument(
        "--key",
        type=str,
        default=None,
        help="Custom SSL private key path (PEM)",
    )
    parser.add_argument(
        "--mock-pi",
        action="store_true",
        help="Run in mock mode without needing a running Raspberry Pi",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    is_ssl = args.ssl
    port = args.port
    if port is None:
        port = 8443 if is_ssl else 8080

    if not WEB_DIR.exists():
        print(f"[ERROR] Web directory not found: {WEB_DIR}", file=sys.stderr)
        return 1

    handler_class = create_request_handler(
        target_pi_url=args.pi,
        web_dir=WEB_DIR,
        mock_mode=args.mock_pi,
    )

    try:
        httpd = HTTPServer((args.host, port), handler_class)
    except OSError as err:
        print(f"[ERROR] Failed to bind to {args.host}:{port}: {err}", file=sys.stderr)
        return 1

    if is_ssl:
        cert_file = Path(args.cert) if args.cert else DEFAULT_CERTS_DIR / "cert.pem"
        key_file = Path(args.key) if args.key else DEFAULT_CERTS_DIR / "key.pem"
        if not (cert_file.exists() and key_file.exists()):
            print("[SSL] Generating self-signed SSL certificates for local LAN...")
            if not ensure_ssl_certificates(cert_file, key_file):
                print(
                    "[ERROR] Failed to generate self-signed certificate. "
                    "Make sure OpenSSL is installed or specify --cert and --key.",
                    file=sys.stderr,
                )
                return 1

        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    local_ips = get_local_ip_addresses()
    print_banner(
        host=args.host,
        port=port,
        is_ssl=is_ssl,
        pi_url=args.pi,
        local_ips=local_ips,
        mock_mode=args.mock_pi,
    )

    try:
        httpd.serve_forever()
        return 0
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Client web server stopped.")
        return 0
    finally:
        httpd.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
