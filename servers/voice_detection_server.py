"""Raspberry Pi Voice Detection & GPIO Hardware Server.

Receives audio recordings over the local network, transcribes them using the local
Vosk speech model, and controls connected GPIO lights and relay. Also supports direct
GPIO signals for instant controls, hardware diagnostics, and multi-client activity logging.
"""

import argparse
import json
import os
import socket
import sys
import time
import urllib.parse
import wave
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Optional


class ThreadedVoiceServer(ThreadingHTTPServer):
    """Multi-threaded voice detection server with TCP_NODELAY enabled."""

    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        sock, addr = super().get_request()
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, AttributeError):
            pass
        return sock, addr


# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.command_parser import check_light_command, get_command_examples
from core.led_controller import LEDController
from core.model_resolver import resolve_model_path
from core.relay import RelayModule


class VoiceCommandServer:
    """Manages Vosk speech transcription and dynamic GPIO actuator control on Raspberry Pi."""

    def __init__(
        self,
        model_path: str,
        light_pin: int = 22,
        yellow_pin: int = 27,
        red_pin: int = 17,
        relay_pin: int = 23,
        active_low: bool = False,
        max_audio_bytes: int = 2_000_000,
    ) -> None:
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as error:
            raise RuntimeError(
                "Missing required Vosk library on the Raspberry Pi.\n"
                "Install it with: pip3 install vosk"
            ) from error

        if max_audio_bytes <= 0:
            raise ValueError("max_audio_bytes must be greater than zero")

        SetLogLevel(-1)
        self.max_audio_bytes = max_audio_bytes
        self.model_path = model_path
        self.model = Model(model_path)
        self.relay = RelayModule(relay_pin, active_low=active_low)
        self.leds = LEDController(
            green_pin=light_pin,
            yellow_pin=yellow_pin,
            red_pin=red_pin,
        )

        # Backwards-compatible attributes
        self.light = self.leds.green
        self.yellow_led = self.leds.yellow
        self.red_led = self.leds.red

        # Initialize all pins to OFF state
        self.relay.off()
        self.leds.reset_all()

        self._recognizer_type = KaldiRecognizer
        self.history: list[dict[str, object]] = []

    def add_history(
        self,
        client_ip: str,
        action_type: str,
        transcript: str,
        command: str,
        message: str,
    ) -> dict[str, object]:
        """Record an action in the shared activity log."""
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

    def process_wav(
        self, audio_bytes: bytes, client_ip: str = "Unknown"
    ) -> dict[str, object]:
        """Transcribe audio bytes and trigger dynamic LED/relay responses."""
        if len(audio_bytes) > self.max_audio_bytes:
            self.leds.system_error_alert()
            raise ValueError("Audio recording exceeds maximum permitted size")

        with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
            if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                self.leds.system_error_alert()
                raise ValueError("Audio must be mono, 16-bit PCM WAV")
            recognizer = self._recognizer_type(self.model, wav_file.getframerate())
            while data := wav_file.readframes(4000):
                recognizer.AcceptWaveform(data)
            result = json.loads(recognizer.FinalResult())

        transcript = result.get("text", "").strip()
        command = check_light_command(transcript)

        # Stop any active recording tally blink on Red LED as audio has arrived
        self.leds.stop_recording()

        if command == "ON":
            self.relay.on()
            self.leds.command_success(final_state=True)
            msg = "Light turned on (dynamic Green response)"
        elif command == "OFF":
            self.relay.off()
            self.leds.command_success(final_state=False)
            msg = "Light turned off (dynamic Green response)"
        else:
            self.leds.command_unknown()
            msg = "No supported light command was recognized (dynamic Yellow fade)"

        self.add_history(client_ip, "VOICE", transcript, command, msg)
        return self.status(transcript=transcript, command=command, message=msg)

    def set_direct(
        self, command: str, client_ip: str = "Unknown"
    ) -> dict[str, object]:
        """Direct GPIO signal command (bypasses speech recognition)."""
        cmd = command.upper()
        if cmd == "ON":
            self.relay.on()
            self.leds.command_success(final_state=True)
            msg = "Light turned on (pure GPIO signal)"
        elif cmd == "OFF":
            self.relay.off()
            self.leds.command_success(final_state=False)
            msg = "Light turned off (pure GPIO signal)"
        else:
            raise ValueError(f"Unsupported direct command: {command}")

        self.add_history(
            client_ip,
            "DIRECT_GPIO",
            f"Pure Signal: Light {cmd}",
            cmd,
            msg,
        )
        return self.status(
            transcript=f"Direct Signal: {cmd}", command=cmd, message=msg
        )

    def set_pin(
        self,
        component: str,
        state: Optional[bool] = None,
        pattern: Optional[str] = None,
        client_ip: str = "Unknown",
    ) -> dict[str, object]:
        """Diagnostic pin toggle or dynamic pattern test for hardware components."""
        comp = component.lower().strip()

        if pattern:
            msg = self.leds.trigger_pattern_test(pattern)
            name = f"Pattern ({pattern})"
            state_str = "PATTERN"
        else:
            state_bool = bool(state)
            state_str = "ON" if state_bool else "OFF"
            if comp == "relay":
                self.relay.on() if state_bool else self.relay.off()
                name = "12V Relay"
                msg = f"{name} set to {state_str}"
            elif comp in ("green", "light", "yellow", "status", "red", "error", "recording", "all"):
                msg = self.leds.set_pin_direct(comp, state_bool)
                name = f"{comp.capitalize()} LED"
            else:
                raise ValueError(f"Unknown hardware component: {component}")

        self.add_history(
            client_ip,
            "PIN_TEST",
            f"Test: {name} {state_str}",
            state_str,
            msg,
        )
        return self.status(
            transcript=f"Test Pin: {name}", command=state_str, message=msg
        )

    def status(
        self,
        transcript: str = "",
        command: str = "UNKNOWN",
        message: Optional[str] = None,
    ) -> dict[str, object]:
        """Return the current logical and physical status of the hardware."""
        default_msg = {
            "ON": "Light turned on",
            "OFF": "Light turned off",
            "UNKNOWN": "No supported light command was recognized",
        }.get(command, "System ready")
        return {
            "transcript": transcript,
            "command": command,
            "light_on": getattr(self.leds.green, "is_lit", False),
            "green_led_on": getattr(self.leds.green, "is_lit", False),
            "relay_on": self.relay.is_on,
            "yellow_led_on": getattr(self.leds.yellow, "is_lit", False),
            "status_led_on": getattr(self.leds.yellow, "is_lit", False),
            "red_led_on": getattr(self.leds.red, "is_lit", False),
            "recording_active": self.leds.is_recording_active(),
            "message": message or default_msg,
        }

    def get_history(self) -> list[dict[str, object]]:
        return list(self.history)

    def clear_history(self) -> None:
        self.history.clear()

    def close(self) -> None:
        """Safely release all GPIO resources."""
        self.relay.off()
        self.relay.close()
        self.leds.close()


def make_handler(controller: VoiceCommandServer):
    """Factory creating the HTTP request handler bound to the controller instance."""

    class RequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def address_string(self) -> str:
            """Avoid slow reverse DNS lookups on LAN client IP addresses."""
            return self.client_address[0]

        def _get_client_ip(self) -> str:
            """Retrieve the true originating client IP address, supporting forward proxies."""
            forwarded = self.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            real_ip = self.headers.get("X-Real-IP")
            if real_ip:
                return real_ip.strip()
            return self.client_address[0]

        def _send_json(self, result: object, status: int = 200) -> None:
            response = json.dumps(result).encode("utf-8")
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, X-Requested-With, X-Forwarded-For, X-Real-IP",
            )
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, X-Requested-With, X-Forwarded-For, X-Real-IP",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            clean_path = urllib.parse.urlparse(self.path).path.rstrip("/")
            if clean_path in ("/status", "/api/status"):
                self._send_json(controller.status())
            elif clean_path in ("/history", "/api/history"):
                self._send_json(controller.get_history())
            elif clean_path in ("/commands", "/api/commands"):
                self._send_json(get_command_examples())
            else:
                self.send_error(404, "Unknown GET endpoint")

        def do_DELETE(self) -> None:
            clean_path = urllib.parse.urlparse(self.path).path.rstrip("/")
            if clean_path in ("/history", "/api/history"):
                controller.clear_history()
                self._send_json({"success": True, "message": "History cleared"})
            else:
                self.send_error(404, "Unknown DELETE endpoint")

        def do_POST(self) -> None:
            clean_path = urllib.parse.urlparse(self.path).path.rstrip("/")
            client_ip = self._get_client_ip()
            content_length_header = self.headers.get("Content-Length")
            try:
                content_length = int(content_length_header or "0")
            except ValueError:
                self.send_error(400, "Content-Length must be an integer")
                return

            if clean_path in ("/recording", "/api/recording"):
                # Voice recording state toggle (drives Red LED recording tally)
                try:
                    payload = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length > 0 else {}
                    is_rec = bool(payload.get("recording", payload.get("state") in ("start", "on", True)))
                    if is_rec:
                        controller.leds.start_recording()
                    else:
                        controller.leds.stop_recording()
                    self._send_json({"success": True, "recording": is_rec})
                    print(
                        f'[RECORDING from {client_ip}] Red LED Tally -> {"BLINKING" if is_rec else "OFF"}',
                        flush=True,
                    )
                except Exception as error:
                    self.send_error(400, f"Recording state error: {error}")
                return

            elif clean_path in ("/audio", "/api/audio"):
                if content_length <= 0 or content_length > controller.max_audio_bytes:
                    controller.leds.stop_recording()
                    controller.leds.system_error_alert()
                    self.send_error(413, "Invalid or oversized audio payload")
                    return

                try:
                    audio_data = self.rfile.read(content_length)
                    result = controller.process_wav(audio_data, client_ip=client_ip)
                except (OSError, ValueError, wave.Error) as error:
                    # REROUTE ERRORS: Rapid warning strobe on Yellow LED
                    controller.leds.stop_recording()
                    controller.leds.system_error_alert()
                    print(f"[AUDIO ERROR from {client_ip}] {error} -> Yellow LED Error Alert", flush=True)
                    self.send_error(400, str(error))
                    return

                self._send_json(result)
                print(
                    f'[VOICE from {client_ip}] "{result["transcript"]}" -> {result["command"]}',
                    flush=True,
                )
                return

            elif clean_path in ("/control", "/api/control", "/quick", "/api/quick"):
                # Pure direct GPIO command (bypasses Vosk speech recognition)
                try:
                    payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    command = payload.get("command", "").upper()
                    result = controller.set_direct(command, client_ip=client_ip)
                    self._send_json(result)
                    print(
                        f'[DIRECT from {client_ip}] Pure Signal -> {command}',
                        flush=True,
                    )
                except Exception as error:
                    self.send_error(400, f"Control error: {error}")
                return

            elif clean_path in ("/gpio", "/api/gpio"):
                # Individual pin test toggle or dynamic pattern test
                try:
                    payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    component = payload.get("component", "")
                    state = payload.get("state", None)
                    pattern = payload.get("pattern", None)
                    result = controller.set_pin(component, state=state, pattern=pattern, client_ip=client_ip)
                    self._send_json(result)
                    print(
                        f'[PIN TEST from {client_ip}] {component} -> pattern:{pattern} state:{state}',
                        flush=True,
                    )
                except Exception as error:
                    self.send_error(400, f"GPIO error: {error}")
                return

            self.send_error(404, "Unknown POST endpoint")

        def log_message(self, format: str, *args) -> None:
            print(f"[HTTP] {format % args}", file=sys.stderr)

    return RequestHandler


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Raspberry Pi Voice Detection and Dynamic GPIO Hardware Server."
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Path to the Vosk speech model directory (automatically detected if omitted)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Network interface to bind on (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Port to listen on (default: 8765)"
    )
    parser.add_argument(
        "--light-pin", type=int, default=22, help="BCM GPIO pin for Green LED (default: 22)"
    )
    parser.add_argument(
        "--relay-pin", type=int, default=23, help="BCM GPIO pin for 12V Relay (default: 23)"
    )
    parser.add_argument(
        "--yellow-pin",
        type=int,
        default=27,
        help="BCM GPIO pin for Yellow Status/Error Alert LED (default: 27)",
    )
    parser.add_argument(
        "--red-pin",
        type=int,
        default=17,
        help="BCM GPIO pin for Red Voice Recording Tally LED (default: 17)",
    )
    parser.add_argument(
        "--active-low",
        action="store_true",
        help="Enable if your relay module is active-low (energizes on LOW signal)",
    )
    return parser.parse_args()


def print_server_banner(host: str, port: int, model_path: str, args: argparse.Namespace) -> None:
    line = "=" * 68
    print("\n" + line)
    print("  [*] RASPBERRY PI VOICE DETECTION & DYNAMIC GPIO SERVER")
    print(line)
    print(f"  * Listening Address:    http://{host}:{port}")
    print(f"  * Speech Model:         {model_path}")
    print(f"  * Green Command Pin:    BCM GPIO {args.light_pin} (Dynamic Recognition Burst)")
    print(f"  * 12V Relay Pin:        BCM GPIO {args.relay_pin} (Active {'Low' if args.active_low else 'High'})")
    print(f"  * Yellow Status/Err Pin:BCM GPIO {args.yellow_pin} (Breathing Fade / Warning Strobe)")
    print(f"  * Red Recording Pin:    BCM GPIO {args.red_pin} (Recording Tally Indicator)")
    print(line)
    print("  Endpoints:")
    print("    POST   /audio     - Send 16kHz Mono WAV recording for Vosk STT")
    print("    POST   /recording - Notify recording state ({\"recording\": true|false})")
    print("    POST   /control   - Direct GPIO signal ({\"command\": \"ON\"|\"OFF\"})")
    print("    POST   /gpio      - Pin/Pattern test ({\"component\": \"...\", \"state\": bool, \"pattern\": \"...\"})")
    print("    GET    /status    - Retrieve current pin and system status")
    print("    GET    /history   - Retrieve activity log from connected devices")
    print("    GET    /commands  - Retrieve list of recognized voice phrases")
    print("    DELETE /history   - Clear activity log")
    print(line + "\n")


def main() -> int:
    arguments = parse_arguments()
    controller: Optional[VoiceCommandServer] = None
    server: Optional[ThreadedVoiceServer] = None
    try:
        # Dynamically discover model path across any project location
        model_path = resolve_model_path(arguments.model)
        print(f"[VOSK] Model path dynamically resolved to: {model_path}")

        controller = VoiceCommandServer(
            model_path,
            light_pin=arguments.light_pin,
            yellow_pin=arguments.yellow_pin,
            red_pin=arguments.red_pin,
            relay_pin=arguments.relay_pin,
            active_low=arguments.active_low,
        )
        server = ThreadedVoiceServer(
            (arguments.host, arguments.port), make_handler(controller)
        )
        print_server_banner(arguments.host, arguments.port, model_path, arguments)
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Voice detection server stopped.")
        return 130
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(f"[STARTUP ERROR] {error}", file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.server_close()
        if controller is not None:
            controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
