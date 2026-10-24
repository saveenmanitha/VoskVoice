import os
import sys
import time
from pathlib import Path

from gpiozero import LED

# Allow this file to be run directly with `python examples/...py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.transcriber import VoskAudioTranscriber
from core.relay import RelayModule

# ==========================================
# GPIO PIN CONFIGURATION (BCM Numbers)
# ==========================================
RED_PIN = 17      # Error: File missing, corrupt, or wrong format
YELLOW_PIN = 27   # Warning: No speech recognized OR unrecognized command
GREEN_PIN = 22    # Command: Turns ON/OFF based on voice commands
RELAY_PIN = 23    # Relay module input for the 12 V light strip

red_led = LED(RED_PIN)
yellow_led = LED(YELLOW_PIN)
green_led = LED(GREEN_PIN)
relay = RelayModule(RELAY_PIN)

# Delays in seconds
DISPLAY_HOLD_DELAY = 3.0   # How long status lights (Red/Yellow) stay lit after processing
INTER_FILE_DELAY = 1.0     # Cooldown pause between audio files

# Raspberry Pi paths
MODEL_PATH = "/home/pi/VOSK/model"
AUDIO_FOLDER = "/home/pi/Vosk_Project/audio"


def print_banner(index: int, total: int, filename: str):
    print("\n" + "=" * 65)
    print(f"  FILE [{index}/{total}]: {filename}")
    print("=" * 65)


def check_light_command(text: str) -> str:
    """
    Parses speech text and returns:
      - 'ON' if an activation command is matched
      - 'OFF' if a deactivation command is matched
      - 'UNKNOWN' if no valid action was requested
    """
    t = text.lower().strip()

    # Phrases to turn the light ON
    on_phrases = [
        "lights on",
        "light on",
        "turn on",
        "turn on light",
        "turn on lights",
        "turn the light on",
        "turn the lights on",
        "switch on"
    ]

    # Phrases to turn the light OFF (including common phonetic misinterpretations)
    off_phrases = [
        "lights off",
        "light off",
        "turn off",
        "turn off light",
        "turn off lights",
        "turn the light off",
        "turn the lights off",
        "switch off",
        "the north"  # Common Vosk mistranscription of "turn off"
    ]

    # 1. Direct phrase matching
    if any(phrase in t for phrase in on_phrases):
        return "ON"
    if any(phrase in t for phrase in off_phrases):
        return "OFF"

    # 2. Token-level keyword matching fallback
    words = set(t.split())
    if ("turn" in words or "switch" in words or "light" in words or "lights" in words):
        if "on" in words:
            return "ON"
        if "off" in words:
            return "OFF"

    return "UNKNOWN"


def handle_file(transcriber: VoskAudioTranscriber, file_path: str):
    filename = os.path.basename(file_path)

    # 1. Error Check & Transcription
    try:
        transcript = transcriber.transcribe_file(file_path)
    except Exception as err:
        # RED LIGHT ACTIVATION
        red_led.on()
        yellow_led.off()
        print(f"  [STATUS] -> 🔴 RED LIGHT (ERROR)")
        print(f"  [DETAIL] -> Failed to process file: {err}")
        print(f"  [HARDWARE] -> Red: ON | Yellow: OFF | Green: {'ON' if green_led.is_lit else 'OFF'}")
        time.sleep(DISPLAY_HOLD_DELAY)
        red_led.off()
        return

    # 2. Yellow Check: No speech detected in audio
    if not transcript:
        yellow_led.on()
        red_led.off()
        print(f"  [STATUS] -> 🟡 YELLOW LIGHT (NO SPEECH DETECTED)")
        print(f"  [DETAIL] -> Audio was valid, but no decipherable words recognized.")
        print(f"  [HARDWARE] -> Red: OFF | Yellow: ON | Green: {'ON' if green_led.is_lit else 'OFF'}")
        time.sleep(DISPLAY_HOLD_DELAY)
        yellow_led.off()
        return

    # 3. Speech detected -> Evaluate command
    print(f"  [TRANSCRIPT] -> \"{transcript}\"")
    command = check_light_command(transcript)

    if command == "ON":
        green_led.on()
        relay.on()
        yellow_led.off()
        red_led.off()
        print(f"  [STATUS] -> 🟢 GREEN LIGHT TOGGLED: ON")
        print(f"  [ACTION] -> Command matched: 'turn on'")
        print(f"  [HARDWARE] -> Red: OFF | Yellow: OFF | Green: ON")
        time.sleep(DISPLAY_HOLD_DELAY)

    elif command == "OFF":
        green_led.off()
        relay.off()
        yellow_led.off()
        red_led.off()
        print(f"  [STATUS] -> ⚪ GREEN LIGHT TOGGLED: OFF")
        print(f"  [ACTION] -> Command matched: 'turn off'")
        print(f"  [HARDWARE] -> Red: OFF | Yellow: OFF | Green: OFF")
        time.sleep(DISPLAY_HOLD_DELAY)

    else:
        # Yellow Check: Speech detected, but no matching command found
        yellow_led.on()
        red_led.off()
        print(f"  [STATUS] -> 🟡 YELLOW LIGHT (UNRECOGNIZED COMMAND)")
        print(f"  [ACTION] -> Heard '{transcript}', but it does not match allowed commands.")
        print(f"  [HARDWARE] -> Red: OFF | Yellow: ON | Green: {'ON' if green_led.is_lit else 'OFF'}")
        time.sleep(DISPLAY_HOLD_DELAY)
        yellow_led.off()


def run_batch_test(model_path: str, audio_folder: str):
    print("*" * 65)
    print("  STARTING RASPBERRY PI AUDIO COMMAND VERIFICATION")
    print("*" * 65)

    try:
        transcriber = VoskAudioTranscriber(model_path)
        audio_files = transcriber.get_audio_files(audio_folder)
    except Exception as e:
        print(f"\n[FATAL STARTUP ERROR] {e}")
        red_led.on()
        time.sleep(4)
        red_led.off()
        return

    if not audio_files:
        print(f"[WARNING] No .wav files found in directory: {audio_folder}")
        yellow_led.on()
        time.sleep(3)
        yellow_led.off()
        return

    total = len(audio_files)
    print(f"Discovered {total} .wav file(s) for batch execution.")

    for idx, file_path in enumerate(audio_files, start=1):
        print_banner(idx, total, os.path.basename(file_path))
        handle_file(transcriber, file_path)
        time.sleep(INTER_FILE_DELAY)

    print("\n" + "*" * 65)
    print("  BATCH TEST COMPLETE — ALL FILES PROCESSED")
    print(f"  FINAL GREEN LED STATE: {'ON' if green_led.is_lit else 'OFF'}")
    print("*" * 65)


if __name__ == "__main__":
    try:
        # Ensure all LEDs start in OFF state
        red_led.off()
        yellow_led.off()
        green_led.off()

        run_batch_test(MODEL_PATH, AUDIO_FOLDER)
    except KeyboardInterrupt:
        print("\n[ABORTED] User terminated execution.")
    finally:
        # Safety clean-up
        red_led.off()
        yellow_led.off()
        green_led.off()
        relay.off()
        red_led.close()
        yellow_led.close()
        green_led.close()
        relay.close()
        print("[SHUTDOWN] GPIO resources released cleanly.")