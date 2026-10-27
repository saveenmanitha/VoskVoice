"""Test voice command transcription and LED/Relay hardware reactions from WAV files.

Can run on a physical Raspberry Pi to test real GPIO outputs, or on any PC/laptop
with simulated GPIO fallback to verify Vosk model accuracy and command parsing.

Usage:
    python tests/test_voice_commands.py
    python tests/test_voice_commands.py audio/turn_on.wav
    python tests/test_voice_commands.py --audio-folder /path/to/audio
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.command_parser import check_light_command
from core.led_controller import LEDController, SimulatedLED
from core.model_resolver import get_audio_dir, resolve_model_path
from core.relay import RelayModule
from core.transcriber import VoskAudioTranscriber


class SimulatedRelay:
    """Fallback simulated Relay for testing on non-Raspberry Pi systems."""

    def __init__(self, pin: int) -> None:
        self.pin = pin
        self.is_on = False

    def on(self) -> None:
        self.is_on = True

    def off(self) -> None:
        self.is_on = False

    def close(self) -> None:
        self.is_on = False


class VoiceCommandTester:
    """Transcribes WAV files with Vosk and validates dynamic hardware LED/Relay responses."""

    RED_PIN = 17
    YELLOW_PIN = 27
    GREEN_PIN = 22
    RELAY_PIN = 23

    def __init__(
        self,
        model_path: Optional[str] = None,
        display_hold_delay: float = 1.5,
        inter_file_delay: float = 0.5,
        is_simulation: bool = False,
    ) -> None:
        self.display_hold_delay = max(0.0, display_hold_delay)
        self.inter_file_delay = max(0.0, inter_file_delay)

        resolved_model = resolve_model_path(model_path)
        print(f"[VOSK] Model dynamically resolved to: {resolved_model}")
        self.transcriber = VoskAudioTranscriber(resolved_model)

        self.is_simulation = is_simulation
        self.leds = LEDController(
            green_pin=self.GREEN_PIN,
            yellow_pin=self.YELLOW_PIN,
            red_pin=self.RED_PIN,
            force_simulation=self.is_simulation,
        )
        self.red_led = self.leds.red
        self.yellow_led = self.leds.yellow
        self.green_led = self.leds.green

        if not self.is_simulation:
            try:
                self.relay = RelayModule(self.RELAY_PIN)
                print("[HARDWARE] Connected to physical Raspberry Pi Relay.")
            except (ImportError, Exception) as err:
                print(f"[INFO] Running simulated Relay ({err}).")
                self.relay = SimulatedRelay(self.RELAY_PIN)
        else:
            self.relay = SimulatedRelay(self.RELAY_PIN)

        self.reset_hardware()

    def reset_hardware(self) -> None:
        """Reset all hardware pins to the OFF state."""
        self.leds.reset_all()
        self.relay.off()

    def close(self) -> None:
        """Release hardware pins safely."""
        self.reset_hardware()
        self.leds.close()
        if hasattr(self.relay, "close"):
            self.relay.close()

    def _hardware_state(self) -> str:
        green_state = "ON" if getattr(self.green_led, "is_lit", False) else "OFF"
        relay_state = "ON" if getattr(self.relay, "is_on", False) else "OFF"
        yellow_state = "ON" if getattr(self.yellow_led, "is_lit", False) else "OFF"
        red_state = "REC_BLINK" if self.leds.is_recording_active() else ("ON" if getattr(self.red_led, "is_lit", False) else "OFF")
        return f"Green: {green_state} | Relay: {relay_state} | Yellow: {yellow_state} | Red: {red_state}"

    def process_audio_file(self, file_path: str) -> dict[str, str]:
        """Process a single WAV audio file and evaluate command execution with dynamic LED reactions."""
        filename = os.path.basename(file_path)
        print(f"\n[AUDIO FILE] {filename}")

        # Start Red LED recording/audio transmission indicator
        self.leds.start_recording()
        print(f"  [HARDWARE] -> Red Recording Tally LIVE | {self._hardware_state()}")

        # 1. Transcription step
        try:
            transcript = self.transcriber.transcribe_file(file_path)
        except Exception as error:
            # Stop Red LED and REROUTE error alert to Yellow LED (rapid warning strobe)
            self.leds.stop_recording()
            self.leds.system_error_alert(blocking=True)
            print(f"  [ERROR] Failed to transcribe: {error}")
            print(f"  [HARDWARE] -> Yellow Rapid Alert Strobe (Rerouted Error) | {self._hardware_state()}")
            time.sleep(self.display_hold_delay)
            return {"file": filename, "transcript": "", "command": "ERROR", "error": str(error)}

        # Transcription complete - stop recording tally blink
        self.leds.stop_recording()

        # 2. Silence / No Speech check
        if not transcript:
            self.leds.command_unknown(blocking=True)
            print("  [STATUS] -> No speech recognized in audio.")
            print(f"  [HARDWARE] -> Yellow Breathing Fade (No Speech) | {self._hardware_state()}")
            time.sleep(self.display_hold_delay)
            return {"file": filename, "transcript": "", "command": "NO_SPEECH"}

        # 3. Command classification
        print(f'  [TRANSCRIPT] -> "{transcript}"')
        command = check_light_command(transcript)

        if command == "ON":
            self.relay.on()
            self.leds.command_success(final_state=True, blocking=True)
            print("  [ACTION] -> Command: ON (Light energized with dynamic Green burst)")
        elif command == "OFF":
            self.relay.off()
            self.leds.command_success(final_state=False, blocking=True)
            print("  [ACTION] -> Command: OFF (Light extinguished with dynamic Green burst)")
        else:
            self.leds.command_unknown(blocking=True)
            print(f"  [ACTION] -> Unrecognized Command: '{transcript}' (Dynamic Yellow fade)")

        print(f"  [HARDWARE] -> {self._hardware_state()}")
        time.sleep(self.display_hold_delay)
        return {"file": filename, "transcript": transcript, "command": command}

    def process_all(self, folder_path: Optional[str] = None) -> list[dict[str, str]]:
        """Run batch tests against all WAV files in the audio folder."""
        folder = get_audio_dir(folder_path)
        audio_files = sorted(folder.glob("*.wav"))

        if not audio_files:
            print(f"[WARNING] No .wav files found in: {folder}")
            return []

        print("\n" + "=" * 68)
        print(f"  RUNNING BATCH VOICE TESTS ({len(audio_files)} files)")
        print(f"  Folder: {folder}")
        print("=" * 68)

        results = []
        for index, file_path in enumerate(audio_files, start=1):
            print(f"\n--- [{index}/{len(audio_files)}] ---")
            res = self.process_audio_file(str(file_path))
            results.append(res)
            if index < len(audio_files):
                time.sleep(self.inter_file_delay)

        print("\n" + "=" * 68)
        print("  TEST SUMMARY RESULTS:")
        print("=" * 68)
        for r in results:
            print(f"  {r['file']:20} -> Transcript: \"{r['transcript']}\" -> Command: {r['command']}")
        print("=" * 68 + "\n")
        return results


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Vosk speech recognition and LED/Relay reactions with sample WAV files."
    )
    parser.add_argument("audio_file", nargs="?", help="Optional single WAV file to test")
    parser.add_argument(
        "--audio-folder",
        default=None,
        help="Path to folder containing .wav files (default: project audio directory)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Path to the Vosk model directory (auto-detected if omitted)",
    )
    parser.add_argument(
        "--hold-delay",
        type=float,
        default=1.5,
        help="Seconds to hold LED state per file (default: 1.5)",
    )
    parser.add_argument(
        "--simulated",
        action="store_true",
        help="Force simulated hardware mode even on Raspberry Pi",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    tester: Optional[VoiceCommandTester] = None
    try:
        tester = VoiceCommandTester(
            model_path=args.model,
            display_hold_delay=args.hold_delay,
            is_simulation=args.simulated,
        )
        if args.audio_file:
            target = Path(args.audio_file)
            if not target.is_file():
                print(f"[ERROR] Audio file not found: {args.audio_file}", file=sys.stderr)
                return 1
            tester.process_audio_file(str(target))
        else:
            tester.process_all(args.audio_folder)
        return 0
    except KeyboardInterrupt:
        print("\n[ABORTED] Test cancelled by user.")
        return 130
    except Exception as error:
        print(f"\n[FATAL ERROR] {error}", file=sys.stderr)
        return 1
    finally:
        if tester is not None:
            tester.close()


if __name__ == "__main__":
    raise SystemExit(main())
