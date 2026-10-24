"""Raspberry Pi server for laptop microphone voice commands.

The server receives short WAV recordings over the local network, transcribes
them with the local Vosk model, and controls the GPIO light.
"""

import argparse
import json
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from typing import Optional

from core.command_parser import check_light_command
from core.relay import RelayModule


class VoiceCommandServer:
    def __init__(
        self,
        model_path: str,
        light_pin: int = 22,
        yellow_pin: int = 27,
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
        self.light.off()
        self.relay.off()
        self.yellow_led.off()
        self._recognizer_type = KaldiRecognizer

    def process_wav(self, audio_bytes: bytes) -> dict[str, object]:
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
        elif command == "OFF":
            self.light.off()
            self.relay.off()
            self.yellow_led.off()
        else:
            self.yellow_led.on()

        return self.status(transcript=transcript, command=command)

    def status(
        self, transcript: str = "", command: str = "UNKNOWN"
    ) -> dict[str, object]:
        return {
            "transcript": transcript,
            "command": command,
            "light_on": self.light.is_active,
            "relay_on": self.relay.is_on,
            "status_led_on": self.yellow_led.is_active,
            "message": {
                "ON": "Light turned on",
                "OFF": "Light turned off",
                "UNKNOWN": "No supported light command was recognized",
            }[command],
        }

    def close(self) -> None:
        self.light.off()
        self.relay.off()
        self.yellow_led.off()
        self.light.close()
        self.relay.close()
        self.yellow_led.close()


def make_handler(controller: VoiceCommandServer):
    class RequestHandler(BaseHTTPRequestHandler):
        def _send_json(self, result: dict[str, object], status: int = 200) -> None:
            response = json.dumps(result).encode("utf-8")
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path != "/status":
                self.send_error(404, "Use GET /status")
                return
            self._send_json(controller.status())

        def do_POST(self) -> None:
            if self.path != "/audio":
                self.send_error(404, "Use POST /audio")
                return

            content_length_header = self.headers.get("Content-Length")
            try:
                content_length = int(content_length_header or "0")
            except ValueError:
                self.send_error(400, "Content-Length must be an integer")
                return
            if content_length <= 0 or content_length > controller.max_audio_bytes:
                self.send_error(413, "Invalid or oversized audio payload")
                return

            try:
                result = controller.process_wav(self.rfile.read(content_length))
            except (OSError, ValueError, wave.Error) as error:
                self.send_error(400, str(error))
                return

            self._send_json(result)
            print(
                f'[REQUEST] "{result["transcript"]}" -> {result["command"]}',
                flush=True,
            )

        def log_message(self, format: str, *args) -> None:
            print(f"[HTTP] {format % args}", file=sys.stderr)

    return RequestHandler


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Receive laptop voice recordings and control a Pi GPIO light."
    )
    parser.add_argument("--model", default="/home/pi/Vosk_Project/vosk-model-small-en-us-0.15")
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
    parser.add_argument("--active-low", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    controller: Optional[VoiceCommandServer] = None
    server: Optional[ThreadingHTTPServer] = None
    try:
        controller = VoiceCommandServer(
            arguments.model,
            arguments.light_pin,
            arguments.yellow_pin,
            arguments.active_low,
            relay_pin=arguments.relay_pin,
        )
        server = ThreadingHTTPServer(
            (arguments.host, arguments.port), make_handler(controller)
        )
        print(
            f"Listening for laptop audio on http://{arguments.host}:{arguments.port}/audio"
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
