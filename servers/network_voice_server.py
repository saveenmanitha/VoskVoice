"""Raspberry Pi server for network voice commands and direct GPIO control.

The server receives short WAV recordings over the local network, transcribes
them with the local Vosk model, controls the GPIO lights and relay, and supports
pure direct GPIO commands for deterministic testing and multi-client activity logging.
"""

import argparse
import json
import sys
import time
import wave
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Optional

# Allow this file to be run directly with `python servers/...py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.command_parser import check_light_command
from core.relay import RelayModule


class VoiceCommandServer:
    def __init__(
        self,
        model_path: str,
        light_pin: int = 22,
        yellow_pin: int = 27,
        red_pin: int = 17,
        active_low: bool = False,
        max_audio_bytes: int = 2_000_000,
        relay_pin: int = 23,
    ) -> None:
        try:
            from gpiozero import LED
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as error:
            raise RuntimeError(
                "Install dependencies on the Pi with: "
                "pip3 install vosk gpiozero"
            ) from error

        if max_audio_bytes <= 0:
            raise ValueError("max_audio_bytes must be greater than zero")
        SetLogLevel(-1)
        self.max_audio_bytes = max_audio_bytes
        self.model = Model(model_path)
        self.light = LED(light_pin)
        self.relay = RelayModule(relay_pin, active_low=active_low)
        self.yellow_led = LED(yellow_pin)
        self.red_led = LED(red_pin)
        self.light.off()
        self.relay.off()
        self.yellow_led.off()
        self.red_led.off()
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
        if len(self.history) > 50:
            self.history.pop()
        return entry

    def process_wav(
        self, audio_bytes: bytes, client_ip: str = "Unknown"
    ) -> dict[str, object]:
        if len(audio_bytes) > self.max_audio_bytes:
            raise ValueError("Audio recording is too large")

        with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
            if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                raise ValueError("Audio must be mono, 16-bit PCM WAV")
            recognizer = self._recognizer_type(self.model, wav_file.getframerate())
            while data := wav_file.readframes(4000):
                recognizer.AcceptWaveform(data)
            result = json.loads(recognizer.FinalResult())

        transcript = result.get("text", "").strip()
        command = check_light_command(transcript)
        if command == "ON":
            self.light.on()
            self.relay.on()
            self.yellow_led.off()
            self.red_led.off()
            msg = "Light turned on and relay energized"
        elif command == "OFF":
            self.light.off()
            self.relay.off()
            self.yellow_led.off()
            self.red_led.off()
            msg = "Light turned off and relay opened"
        else:
            self.yellow_led.on()
            self.red_led.off()
            msg = "No supported light command was recognized"

        self.add_history(client_ip, "VOICE", transcript, command, msg)
        return self.status(transcript=transcript, command=command, message=msg)

    def set_direct(
        self, command: str, client_ip: str = "Unknown"
    ) -> dict[str, object]:
        cmd = command.upper()
        if cmd == "ON":
            self.light.on()
            self.relay.on()
            self.yellow_led.off()
            self.red_led.off()
            msg = "Light turned on (pure GPIO signal)"
        elif cmd == "OFF":
            self.light.off()
            self.relay.off()
            self.yellow_led.off()
            self.red_led.off()
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
        self, component: str, state: bool, client_ip: str = "Unknown"
    ) -> dict[str, object]:
        comp = component.lower().strip()
        state_str = "ON" if state else "OFF"

        if comp in ("green", "light"):
            self.light.on() if state else self.light.off()
            name = "Green LED"
        elif comp == "relay":
            self.relay.on() if state else self.relay.off()
            name = "12V Relay"
        elif comp in ("yellow", "status"):
            self.yellow_led.on() if state else self.yellow_led.off()
            name = "Yellow Status LED"
        elif comp in ("red", "error"):
            self.red_led.on() if state else self.red_led.off()
            name = "Red Error LED"
        elif comp == "all":
            if state:
                self.light.on()
                self.relay.on()
                self.yellow_led.on()
                self.red_led.on()
            else:
                self.light.off()
                self.relay.off()
                self.yellow_led.off()
                self.red_led.off()
            name = "All Hardware Pins"
        else:
            raise ValueError(f"Unknown hardware component: {component}")

        msg = f"{name} set to {state_str}"
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
        default_msg = {
            "ON": "Light turned on",
            "OFF": "Light turned off",
            "UNKNOWN": "No supported light command was recognized",
        }.get(command, "System ready")
        return {
            "transcript": transcript,
            "command": command,
            "light_on": self.light.is_active,
            "relay_on": self.relay.is_on,
            "yellow_led_on": self.yellow_led.is_active,
            "status_led_on": self.yellow_led.is_active,
            "red_led_on": self.red_led.is_active,
            "message": message or default_msg,
        }

    def get_history(self) -> list[dict[str, object]]:
        return list(self.history)

    def clear_history(self) -> None:
        self.history.clear()

    def close(self) -> None:
        self.light.off()
        self.relay.off()
        self.yellow_led.off()
        self.red_led.off()
        self.light.close()
        self.relay.close()
        self.yellow_led.close()
        self.red_led.close()


def make_handler(controller: VoiceCommandServer):
    class RequestHandler(BaseHTTPRequestHandler):
        def _send_json(self, result: object, status: int = 200) -> None:
            response = json.dumps(result).encode("utf-8")
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-Requested-With"
            )
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
                "Access-Control-Allow-Headers", "Content-Type, X-Requested-With"
            )
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/status":
                self._send_json(controller.status())
            elif self.path == "/history":
                self._send_json(controller.get_history())
            elif self.path == "/commands":
                from core.command_parser import get_command_examples
                self._send_json(get_command_examples())
            else:
                self.send_error(404, "Unknown GET endpoint")

        def do_DELETE(self) -> None:
            if self.path == "/history":
                controller.clear_history()
                self._send_json({"success": True, "message": "History cleared"})
            else:
                self.send_error(404, "Unknown DELETE endpoint")

        def do_POST(self) -> None:
            client_ip = self.client_address[0]
            content_length_header = self.headers.get("Content-Length")
            try:
                content_length = int(content_length_header or "0")
            except ValueError:
                self.send_error(400, "Content-Length must be an integer")
                return

            if self.path == "/audio":
                if content_length <= 0 or content_length > controller.max_audio_bytes:
                    self.send_error(413, "Invalid or oversized audio payload")
                    return

                try:
                    audio_data = self.rfile.read(content_length)
                    result = controller.process_wav(audio_data, client_ip=client_ip)
                except (OSError, ValueError, wave.Error) as error:
                    self.send_error(400, str(error))
                    return

                self._send_json(result)
                print(
                    f'[VOICE from {client_ip}] "{result["transcript"]}" -> {result["command"]}',
                    flush=True,
                )
                return

            elif self.path == "/control":
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

            elif self.path == "/gpio":
                # Individual pin test toggle (Green, Relay, Yellow, Red)
                try:
                    payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    component = payload.get("component", "")
                    state = bool(payload.get("state", False))
                    result = controller.set_pin(
                        component, state, client_ip=client_ip
                    )
                    self._send_json(result)
                    print(
                        f'[PIN TEST from {client_ip}] {component} -> {"ON" if state else "OFF"}',
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
        description="Receive laptop voice recordings and control a Pi GPIO light."
    )
    parser.add_argument(
        "--model", default="/home/pi/Vosk_Project/vosk-model-small-en-us-0.15"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Interface to listen on")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--light-pin", type=int, default=22)
    parser.add_argument("--relay-pin", type=int, default=23)
    parser.add_argument(
        "--yellow-pin",
        type=int,
        default=27,
        help="BCM GPIO pin for unrecognized-command status (default: 27)",
    )
    parser.add_argument(
        "--red-pin",
        type=int,
        default=17,
        help="BCM GPIO pin for error status (default: 17)",
    )
    parser.add_argument("--active-low", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    controller: Optional[VoiceCommandServer] = None
    server: Optional[ThreadingHTTPServer] = None
    try:
        controller = VoiceCommandServer(
            arguments.model,
            light_pin=arguments.light_pin,
            yellow_pin=arguments.yellow_pin,
            red_pin=arguments.red_pin,
            active_low=arguments.active_low,
            relay_pin=arguments.relay_pin,
        )
        server = ThreadingHTTPServer(
            (arguments.host, arguments.port), make_handler(controller)
        )
        print(
            f"Listening for commands on http://{arguments.host}:{arguments.port} (audio & direct GPIO)"
        )
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Server stopped.")
        return 130
    except (OSError, RuntimeError, ValueError) as error:
        print(f"[STARTUP ERROR] {error}", file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.server_close()
        if controller is not None:
            controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
