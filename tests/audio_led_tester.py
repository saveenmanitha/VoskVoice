"""Test Raspberry Pi LED responses to commands in WAV audio files.

Usage:
    python3 -m tests.audio_led_tester /path/to/command.wav
    python3 -m tests.audio_led_tester --audio-folder /path/to/audio
"""

import argparse
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

# Allow this file to be run directly with `python tests/...py`.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.command_parser import check_light_command
from core.transcriber import VoskAudioTranscriber
from core.relay import RelayModule


class AudioLedTester:
    """Transcribe audio files and display the result on three LEDs."""

    RED_PIN = 17
    YELLOW_PIN = 27
    GREEN_PIN = 22
    RELAY_PIN = 23

    def __init__(
        self,
        model_path: str,
        display_hold_delay: float = 3.0,
        inter_file_delay: float = 1.0,
        led_factory: Optional[Callable[[int], Any]] = None,
        relay: Optional[RelayModule] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if display_hold_delay < 0 or inter_file_delay < 0:
            raise ValueError("LED delays cannot be negative")

        if led_factory is None:
            try:
                from gpiozero import LED
            except ImportError as error:
                raise RuntimeError(
                    "gpiozero is required to control LEDs. "
                    "Install it on the Raspberry Pi with: pip3 install gpiozero"
                ) from error
            led_factory = LED

        self.display_hold_delay = display_hold_delay
        self.inter_file_delay = inter_file_delay
        self._sleep = sleep
        self.transcriber = VoskAudioTranscriber(model_path)
        self.red_led = led_factory(self.RED_PIN)
        self.yellow_led = led_factory(self.YELLOW_PIN)
        self.green_led = led_factory(self.GREEN_PIN)
        self.relay = relay or RelayModule(self.RELAY_PIN)
        self.reset_leds()

    def reset_leds(self) -> None:
        """Turn all status LEDs off without changing the logical light state."""
        self.red_led.off()
        self.yellow_led.off()
        self.green_led.off()
        self.relay.off()

    def close(self) -> None:
        """Leave the GPIO pins safe and release their resources."""
        self.reset_leds()
        self.red_led.close()
        self.yellow_led.close()
        self.green_led.close()
        self.relay.close()

    def check_light_command(self, text: str) -> str:
        """Return ``ON``, ``OFF``, or ``UNKNOWN`` for transcribed speech."""
        return check_light_command(text)

    def _hardware_state(self) -> str:
        return (
            f"Red: {'ON' if self.red_led.is_lit else 'OFF'} | "
            f"Yellow: {'ON' if self.yellow_led.is_lit else 'OFF'} | "
            f"Green: {'ON' if self.green_led.is_lit else 'OFF'}"
        )

    def _show_error(self, error: Exception) -> None:
        self.red_led.on()
        self.yellow_led.off()
        print("  [STATUS] -> RED LIGHT (ERROR)")
        print(f"  [DETAIL] -> Failed to process file: {error}")
        print(f"  [HARDWARE] -> {self._hardware_state()}")
        self._sleep(self.display_hold_delay)
        self.red_led.off()

    def _show_no_speech(self) -> None:
        self.yellow_led.on()
        self.red_led.off()
        print("  [STATUS] -> YELLOW LIGHT (NO SPEECH DETECTED)")
        print("  [DETAIL] -> Audio was valid, but no decipherable words recognized.")
        print(f"  [HARDWARE] -> {self._hardware_state()}")
        self._sleep(self.display_hold_delay)
        self.yellow_led.off()

    def process_audio_file(self, file_path: str) -> str:
        """Process one WAV file and return its result category."""
        print(f"\n[FILE] {os.path.basename(file_path)}")

        try:
            transcript = self.transcriber.transcribe_file(file_path)
        except Exception as error:
            self._show_error(error)
            return "ERROR"

        if not transcript:
            self._show_no_speech()
            return "NO_SPEECH"

        print(f'  [TRANSCRIPT] -> "{transcript}"')
        command = self.check_light_command(transcript)

        if command == "ON":
            self.green_led.on()
            self.relay.on()
            self.yellow_led.off()
            self.red_led.off()
            print("  [STATUS] -> GREEN LIGHT TOGGLED: ON")
            print("  [ACTION] -> Command matched: 'turn on'")
        elif command == "OFF":
            self.green_led.off()
            self.relay.off()
            self.yellow_led.off()
            self.red_led.off()
            print("  [STATUS] -> GREEN LIGHT TOGGLED: OFF")
            print("  [ACTION] -> Command matched: 'turn off'")
        else:
            self.yellow_led.on()
            self.red_led.off()
            print("  [STATUS] -> YELLOW LIGHT (UNRECOGNIZED COMMAND)")
            print(
                f"  [ACTION] -> Heard '{transcript}', "
                "but it does not match allowed commands."
            )

        print(f"  [HARDWARE] -> {self._hardware_state()}")
        self._sleep(self.display_hold_delay)
        if command == "UNKNOWN":
            self.yellow_led.off()
        return command

    def process_audio_folder(self, audio_folder: str) -> list[str]:
        """Process every WAV file in a folder and return each result category."""
        audio_files = self.transcriber.get_audio_files(audio_folder)
        if not audio_files:
            raise FileNotFoundError(f"No .wav files found in directory: {audio_folder}")

        results = []
        for index, file_path in enumerate(audio_files, start=1):
            print(f"\n{'=' * 65}")
            print(f"  FILE [{index}/{len(audio_files)}]: {os.path.basename(file_path)}")
            print("=" * 65)
            results.append(self.process_audio_file(file_path))
            if index < len(audio_files):
                self._sleep(self.inter_file_delay)
        return results


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test Raspberry Pi LED responses to WAV audio commands."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("audio_file", nargs="?", help="WAV file to test")
    input_group.add_argument(
        "--audio-folder",
        help="Process every WAV file in a folder instead of one audio file",
    )
    parser.add_argument(
        "--model",
        default="/home/pi/VOSK/model",
        help="Path to the Vosk model (default: /home/pi/VOSK/model)",
    )
    parser.add_argument(
        "--hold-delay",
        type=float,
        default=3.0,
        help="Seconds to display each result (default: 3)",
    )
    parser.add_argument(
        "--inter-file-delay",
        type=float,
        default=1.0,
        help="Seconds between files in folder mode (default: 1)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    tester: Optional[AudioLedTester] = None
    try:
        tester = AudioLedTester(
            model_path=arguments.model,
            display_hold_delay=arguments.hold_delay,
            inter_file_delay=arguments.inter_file_delay,
        )
        if arguments.audio_file:
            if not Path(arguments.audio_file).is_file():
                raise FileNotFoundError(f"Audio file not found: {arguments.audio_file}")
            tester.process_audio_file(arguments.audio_file)
        else:
            tester.process_audio_folder(arguments.audio_folder)
        return 0
    except KeyboardInterrupt:
        print("\n[ABORTED] User terminated execution.")
        return 130
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as error:
        print(f"\n[STARTUP ERROR] {error}")
        if tester is not None:
            tester.red_led.on()
            tester._sleep(tester.display_hold_delay)
        return 1
    finally:
        if tester is not None:
            tester.close()
            print("[SHUTDOWN] GPIO resources released cleanly.")


if __name__ == "__main__":
    raise SystemExit(main())
