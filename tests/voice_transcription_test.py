import os
import time
from gpiozero import LED
from core.transcriber import VoskAudioTranscriber
from core.relay import RelayModule

# ==========================================
# GPIO PIN CONFIGURATION (BCM Numbers)
# ==========================================
RED_PIN = 17      # Error: File missing, corrupt, or wrong format
YELLOW_PIN = 27   # Warning: No speech recognized
GREEN_PIN = 22    # Command: Turns ON/OFF based on voice commands
RELAY_PIN = 23

red_led = LED(RED_PIN)
yellow_led = LED(YELLOW_PIN)
green_led = LED(GREEN_PIN)
relay = RelayModule(RELAY_PIN)

# Delays in seconds
DISPLAY_HOLD_DELAY = 3.0   # How long status lights (Red/Yellow) stay lit after processing
INTER_FILE_DELAY = 1.0     # Cooldown pause between audio files

# Raspberry Pi paths (update to match your exact paths)
MODEL_PATH = "/home/pi/vosk-model-small-en-us-0.15"
AUDIO_FOLDER = "/home/pi/audio_tests"


def print_banner(index: int, total: int, filename: str):
    print("\n" + "=" * 65)
    print(f"  FILE [{index}/{total}]: {filename}")
    print("=" * 65)


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

    # 2. Yellow Check (No speech detected)
    if not transcript:
        yellow_led.on()
        red_led.off()
        print(f"  [STATUS] -> 🟡 YELLOW LIGHT (NO SPEECH DETECTED)")
        print(f"  [DETAIL] -> Audio was valid, but no decipherable words recognized.")
        print(f"  [HARDWARE] -> Red: OFF | Yellow: ON | Green: {'ON' if green_led.is_lit else 'OFF'}")
        time.sleep(DISPLAY_HOLD_DELAY)
        yellow_led.off()
        return

    # 3. Green Evaluation (Speech detected)
    print(f"  [TRANSCRIPT] -> \"{transcript}\"")
    normalized_text = transcript.lower()

    if "turn on" in normalized_text or "turn on light" in normalized_text:
        green_led.on()
        relay.on()
        print(f"  [STATUS] -> 🟢 GREEN LIGHT TOGGLED: ON")
        print(f"  [ACTION] -> Command matched: 'turn on'")
    elif "turn off" in normalized_text or "turn off light" in normalized_text:
        green_led.off()
        relay.off()
        print(f"  [STATUS] -> ⚪ GREEN LIGHT TOGGLED: OFF")
        print(f"  [ACTION] -> Command matched: 'turn off'")
    else:
        print(f"  [STATUS] -> ⚪ NO MATCHING ACTION")
        print(f"  [ACTION] -> Speech parsed, but not an ON/OFF command. Green state preserved.")

    # Status indicators remain off; show current Green light state
    red_led.off()
    yellow_led.off()
    print(f"  [HARDWARE] -> Red: OFF | Yellow: OFF | Green: {'ON' if green_led.is_lit else 'OFF'}")
    time.sleep(DISPLAY_HOLD_DELAY)


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
        # All LEDs OFF initially
        red_led.off()
        yellow_led.off()
        green_led.off()

        run_batch_test(MODEL_PATH, AUDIO_FOLDER)
    except KeyboardInterrupt:
        print("\n[ABORTED] User terminated execution.")
    finally:
        # Safety turn-off
        red_led.off()
        yellow_led.off()
        green_led.off()
        relay.off()
        red_led.close()
        yellow_led.close()
        green_led.close()
        relay.close()
        print("[SHUTDOWN] GPIO resources released cleanly.")