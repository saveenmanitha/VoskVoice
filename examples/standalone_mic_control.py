"""Standalone offline voice controller using a microphone directly connected to the Raspberry Pi.

This example runs entirely on the Raspberry Pi without requiring the client web server
or local network connections. Utterances from a USB mic are recognized by the local Vosk
model and directly control the GPIO pins.
"""

import argparse
import json
import queue
import sys
from pathlib import Path
from typing import Optional

# Allow running directly with `python examples/standalone_mic_control.py`
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.command_parser import check_light_command
from core.model_resolver import resolve_model_path
from core.relay import RelayModule


class StandaloneVoiceLightController:
    """Recognize local microphone speech and control GPIO outputs."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        light_pin: int = 22,
        relay_pin: int = 23,
        sample_rate: int = 16000,
        device: Optional[int] = None,
        active_low: bool = False,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be greater than zero")

        try:
            import sounddevice as sd
        except ImportError as error:
            raise RuntimeError(
                "sounddevice is required for live microphone input.\n"
                "Install it on the Raspberry Pi with: pip3 install sounddevice"
            ) from error
        try:
            from gpiozero import LED
        except ImportError as error:
            raise RuntimeError(
                "gpiozero is required for GPIO control.\n"
                "Install it on the Raspberry Pi with: pip3 install gpiozero"
            ) from error
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as error:
            raise RuntimeError(
                "vosk is required for speech recognition.\n"
                "Install it on the Raspberry Pi with: pip3 install vosk"
            ) from error

        SetLogLevel(-1)
        self.resolved_model_path = resolve_model_path(model_path)
        print(f"[VOSK] Model path dynamically resolved to: {self.resolved_model_path}")

        self._sounddevice = sd
        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self.sample_rate = sample_rate
        self.device = device
        self.recognizer = KaldiRecognizer(Model(self.resolved_model_path), sample_rate)
        self.light = LED(light_pin)
        self.relay = RelayModule(relay_pin, active_low=active_low)
        self.light.off()
        self.relay.off()

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[AUDIO WARNING] {status}", file=sys.stderr)
        self._audio_queue.put(bytes(indata))

    def _apply_command(self, transcript: str) -> None:
        command = check_light_command(transcript)
        if command == "ON":
            self.light.on()
            self.relay.on()
            print("  [ACTION] Light turned ON (Relay energized)")
        elif command == "OFF":
            self.light.off()
            self.relay.off()
            print("  [ACTION] Light turned OFF (Relay opened)")
        else:
            print(f"  [ACTION] Ignored: '{transcript}' is not an ON/OFF light command")

    def run(self) -> None:
        """Listen continuously until Ctrl+C and apply recognized commands."""
        print("\n" + "=" * 65)
        print("  STANDALONE PI MICROPHONE VOICE CONTROLLER")
        print("=" * 65)
        print("  Speak naturally into the Pi microphone:")
        print("    - 'turn on the light' / 'lights on'")
        print("    - 'turn off the light' / 'lights off'")
        print("  Press Ctrl+C to stop listening.")
        print("=" * 65 + "\n")

        with self._sounddevice.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=8000,
            device=self.device,
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
        ):
            while True:
                audio_data = self._audio_queue.get()
                if self.recognizer.AcceptWaveform(audio_data):
                    result = json.loads(self.recognizer.Result())
                    transcript = result.get("text", "").strip()
                    if transcript:
                        print(f'[TRANSCRIPT] "{transcript}"')
                        self._apply_command(transcript)

    def close(self) -> None:
        """Turn actuators off and safely release GPIO resources."""
        self.light.off()
        self.relay.off()
        self.light.close()
        self.relay.close()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone offline voice control using a microphone plugged directly into the Raspberry Pi."
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Path to the Vosk speech model directory (automatically detected if omitted)",
    )
    parser.add_argument(
        "--light-pin",
        type=int,
        default=22,
        help="BCM GPIO pin for Green LED (default: 22)",
    )
    parser.add_argument(
        "--relay-pin",
        type=int,
        default=23,
        help="BCM GPIO pin for 12V Relay (default: 23)",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="Microphone sample rate in Hz (default: 16000)",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Optional sounddevice input device index",
    )
    parser.add_argument(
        "--active-low",
        action="store_true",
        help="Enable if your relay module energizes on LOW signal",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    controller: Optional[StandaloneVoiceLightController] = None
    try:
        controller = StandaloneVoiceLightController(
            model_path=arguments.model,
            light_pin=arguments.light_pin,
            relay_pin=arguments.relay_pin,
            sample_rate=arguments.sample_rate,
            device=arguments.device,
            active_low=arguments.active_low,
        )
        controller.run()
        return 0
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Microphone listening stopped.")
        return 130
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(f"\n[STARTUP ERROR] {error}", file=sys.stderr)
        return 1
    finally:
        if controller is not None:
            controller.close()
            print("[SHUTDOWN] GPIO resources released cleanly.")


if __name__ == "__main__":
    raise SystemExit(main())
