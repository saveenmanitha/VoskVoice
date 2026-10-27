"""Local network web server and proxy for the Vosk Raspberry Pi Voice Controller.

This server hosts the modern web client and acts as a local proxy between client
devices (smartphones, tablets, laptops) on your local network and the Raspberry Pi.

By proxying API calls, it eliminates browser Mixed Content (HTTPS/HTTP) blocks,
solves CORS issues, and enables secure microphone access (WebRTC/getUserMedia)
across all devices on your Wi-Fi network.
"""

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
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
WEB_DIR = PROJECT_ROOT / "clients" / "web"
AUDIO_DIR = PROJECT_ROOT / "audio"
DEFAULT_CERTS_DIR = PROJECT_ROOT / "certs"


def get_local_ip_addresses() -> list[str]:
    """Return all non-loopback IPv4 addresses for this machine."""
    ips = set()
    # Strategy 1: Connect to an external address via UDP socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass

    # Strategy 2: Query getaddrinfo for local hostname
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
    """Simulated Pi hardware state for testing without physical Pi."""

    def __init__(self) -> None:
        self.light_on = False
        self.relay_on = False
        self.status_led_on = False
        self.last_transcript = ""
        self.last_command = "OFF"
        self.message = "System ready (Mock Mode)"

    def get_status(self) -> dict:
        return {
            "transcript": self.last_transcript,
            "command": self.last_command,
            "light_on": self.light_on,
            "relay_on": self.relay_on,
            "status_led_on": self.status_led_on,
            "message": self.message,
            "mock": True,
        }

    def process_command(self, transcript: str, command: str) -> dict:
        self.last_transcript = transcript
        self.last_command = command
        if command == "ON":
            self.light_on = True
            self.relay_on = True
            self.status_led_on = False
            self.message = "Light turned on (simulated)"
        elif command == "OFF":
            self.light_on = False
            self.relay_on = False
            self.status_led_on = False
            self.message = "Light turned off (simulated)"
        else:
            self.status_led_on = True
            self.message = "No supported light command recognized (simulated)"
        return self.get_status()


def create_request_handler(
    target_pi_url: str,
    web_dir: Path,
    mock_mode: bool = False,
):
    current_pi_url = [target_pi_url.rstrip("/")]
    mock_state = MockPiState() if mock_mode else None

    class WebClientRequestHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_dir), **kwargs)

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT"
            )
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-Requested-With"
            )

        def _send_json_response(self, data: dict, status: int = 200) -> None:
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

            # Default to serving static files from clients/web
            super().do_GET()

        def do_POST(self) -> None:
            if self.path == "/api/audio":
                self._handle_post_audio()
                return
            elif self.path == "/api/config":
                self._handle_post_config()
                return
            elif self.path == "/api/quick":
                self._handle_post_quick()
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

        def _handle_post_audio(self) -> None:
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
                # In mock mode, detect if it's likely a command or return simulated ON
                res = mock_state.process_command(
                    "turn on the light", "ON" if not mock_state.light_on else "OFF"
                )
                self._send_json_response(res)
                return

            # Forward to Pi server
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

        def _handle_post_quick(self) -> None:
            """Execute a quick command using sample WAV files or direct action."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                cmd = payload.get("command", "").upper()
            except Exception:
                cmd = "ON"

            sample_file = None
            if cmd == "ON":
                for name in ["lights_on.wav", "light on.wav", "turn on.wav"]:
                    p = AUDIO_DIR / name
                    if p.exists():
                        sample_file = p
                        break
            elif cmd == "OFF":
                for name in ["lights off.wav", "light off.wav", "turn off.wav"]:
                    p = AUDIO_DIR / name
                    if p.exists():
                        sample_file = p
                        break

            if sample_file and sample_file.exists():
                audio_bytes = sample_file.read_bytes()
                if mock_state is not None:
                    res = mock_state.process_command(
                        "turn on the light" if cmd == "ON" else "turn off the light",
                        cmd,
                    )
                    self._send_json_response(res)
                    return

                # Send sample WAV to Pi
                url = f"{current_pi_url[0]}/audio"
                req = urllib.request.Request(
                    url,
                    data=audio_bytes,
                    headers={"Content-Type": "audio/wav"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=10) as response:
                        data = json.loads(response.read().decode("utf-8"))
                        self._send_json_response(data, status=response.status)
                except Exception as err:
                    self._send_json_response({"error": str(err)}, status=502)
            else:
                self._send_json_response(
                    {"error": f"No audio sample available for command: {cmd}"},
                    status=404,
                )

        def log_message(self, format: str, *args) -> None:
            # Clean logging
            sys.stderr.write(f"[WEB SERVER] {format % args}\n")

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
    print("  [*] VOSK PI VOICE CONTROLLER - LOCAL CLIENT WEB SERVER")
    print(line)
    print(f"  * Local Machine:   {protocol}://localhost:{port}")
    if local_ips:
        for ip in local_ips:
            print(f"  * LAN Network:     {protocol}://{ip}:{port}")
    else:
        print(f"  * LAN Network:     {protocol}://{host}:{port}")
    print(f"  * Target Pi Server:{pi_url}")
    if mock_mode:
        print("  * Mode:            SIMULATED MOCK PI (Physical Pi not required)")
    else:
        print("  * Mode:            LIVE PROXY (Forwarding audio/status to Pi)")
    print(line)
    print("  [>] Device Access Instructions:")
    print("  1. Connect your phone or tablet to the same Wi-Fi network.")
    if is_ssl:
        print(f"  2. Open {protocol}://{local_ips[0] if local_ips else host}:{port}")
        print("  3. Bypass the self-signed certificate warning (Advanced -> Proceed).")
        print("     This enables microphone access across local network devices!")
    else:
        print(f"  2. Open {protocol}://{local_ips[0] if local_ips else host}:{port}")
        print("     Note: To record microphone on mobile devices, run with --ssl")
        print("     or enable insecure origin in chrome://flags.")
    print("  4. Press and hold the mic button or use Auto-Detect to control the light!")
    print(line + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Host the client web interface on the local network."
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
        help="Pi server URL (default: http://raspberrypi.local:8765)",
    )
    parser.add_argument(
        "--ssl",
        "--https",
        action="store_true",
        help="Enable HTTPS with self-signed certificate (allows mobile mic access)",
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
        help="Run in mock mode without needing a running Pi",
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
