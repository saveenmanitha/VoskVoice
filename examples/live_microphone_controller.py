"""Control a Raspberry Pi light from live microphone speech.

The microphone, Vosk model, and GPIO actuator are all local to the Pi.
"""

import argparse
import json
import queue
import sys
from pathlib import Path
from typing import Optional

# Allow this file to be run directly with `python examples/...py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.command_parser import check_light_command
from core.relay import RelayModule


class LiveVoiceLightController:
    """Recognize finalized microphone utterances and control one GPIO output."""

    def __init__(
        self,
        model_path: str,
        light_pin: int = 22,
        sample_rate: int = 16000,
        device: Optional[int] = None,
        active_low: bool = False,
        relay_pin: int = 23,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be greater than zero")

        try:
            import sounddevice as sd
        except ImportError as error:
            raise RuntimeError(
                "sounddevice is required for live microphone input. "
                "Install it on the Raspberry Pi with: pip3 install sounddevice"
            ) from error
        try:
            from gpiozero import LED
        except ImportError as error:
            raise RuntimeError(
                "gpiozero is required for GPIO control. "
                "Install it on the Raspberry Pi with: pip3 install gpiozero"
            ) from error
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as error:
            raise RuntimeError(
                "vosk is required for speech recognition. "
                "Install it on the Raspberry Pi with: pip3 install vosk"
            ) from error

        SetLogLevel(-1)
        self._sounddevice = sd
        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self.sample_rate = sample_rate
        self.device = device
        self.recognizer = KaldiRecognizer(Model(model_path), sample_rate)
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
            print("  [ACTION] Light ON")
        elif command == "OFF":
            self.light.off()
            self.relay.off()
            print("  [ACTION] Light OFF")
        else:
            print("  [ACTION] Ignored: not an ON/OFF light command")

    def run(self) -> None:
        """Listen until Ctrl+C and apply recognized light commands."""
        print("Listening for commands. Say 'turn on the light' or 'turn off the light'.")
        print("Press Ctrl+C to stop.")
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
        """Turn the actuator off and release GPIO resources."""
        self.light.off()
        self.relay.off()
        self.light.close()
        self.relay.close()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Control a Raspberry Pi light using live Vosk speech recognition."
    )
    parser.add_argument(
        "--model",
        default="/home/pi/Vosk_Project/vosk-model-small-en-us-0.15",
        help="Path to the Vosk model",
    )
    parser.add_argument(
        "--light-pin",
        type=int,
        default=22,
        help="BCM GPIO pin connected to the LED/relay input (default: 22)",
    )
    parser.add_argument(
        "--relay-pin",
        type=int,
        default=23,
        help="BCM GPIO pin connected to the relay input (default: 23)",
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
        help="Use this for relay modules that turn on when GPIO is LOW",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    controller: Optional[LiveVoiceLightController] = None
    try:
        controller = LiveVoiceLightController(
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
        print("\n[SHUTDOWN] User stopped listening.")
        return 130
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(f"\n[STARTUP ERROR] {error}", file=sys.stderr)
        return 1
    finally:
        if controller is not None:
            controller.close()
            print("[SHUTDOWN] GPIO resources released safely.")


if __name__ == "__main__":
    raise SystemExit(main())
