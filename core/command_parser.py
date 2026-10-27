"""Translate Vosk transcripts into supported light actions with extensive aliases."""

import re
import string
from typing import Dict, List

# Primary direct & phonetic phrase aliases
ON_PHRASES = (
    # Direct phrases
    "lights on",
    "light on",
    "turn on",
    "turn on light",
    "turn on lights",
    "turn on the light",
    "turn on the lights",
    "turn on all lights",
    "turn on all the lights",
    "turn the light on",
    "turn the lights on",
    "turn all lights on",
    "turn it on",
    "turn them on",
    "turn lights on",
    # Switch phrases
    "switch on",
    "switch on light",
    "switch on lights",
    "switch on the light",
    "switch on the lights",
    "switch the light on",
    "switch the lights on",
    "switch it on",
    "switch lights on",
    # Power and activation
    "power on",
    "power on light",
    "power on lights",
    "power on the light",
    "power on the lights",
    "power the light on",
    "power up",
    "activate light",
    "activate lights",
    "activate the light",
    "activate the lights",
    "activate relay",
    "enable light",
    "enable lights",
    # Casual & expressive
    "light up",
    "lights up",
    "illuminate",
    "illumination on",
    "brighten",
    "brighten up",
    "put on the light",
    "put on the lights",
    "put the light on",
    "put the lights on",
    "lights please",
    "light please",
    "wake up",
    "wake the light",
    # Component specific
    "lamp on",
    "turn on lamp",
    "turn on the lamp",
    "strip on",
    "relay on",
    "led on",
    "green light on",
    "green led on",
    # Vosk small model common phonetic misrecognitions
    "ten on",
    "to non",
    "torn on",
    "tour on",
    "tune on",
    "term on",
    "lite on",
    "line on",
    "like on",
    "lights or",
    "light or",
    "the unknown",
)

OFF_PHRASES = (
    # Direct phrases
    "lights off",
    "light off",
    "turn off",
    "turn off light",
    "turn off lights",
    "turn off the light",
    "turn off the lights",
    "turn off all lights",
    "turn off all the lights",
    "turn the light off",
    "turn the lights off",
    "turn all lights off",
    "turn it off",
    "turn them off",
    "turn lights off",
    # Switch phrases
    "switch off",
    "switch off light",
    "switch off lights",
    "switch off the light",
    "switch off the lights",
    "switch the light off",
    "switch the lights off",
    "switch it off",
    "switch lights off",
    # Power and deactivation
    "power off",
    "power off light",
    "power off lights",
    "power off the light",
    "power off the lights",
    "power down",
    "power down the light",
    "shut off",
    "shut off light",
    "shut off lights",
    "shut off the light",
    "shut off the lights",
    "shut the light off",
    "shut the lights off",
    "shut down the light",
    "shut down lights",
    "deactivate light",
    "deactivate lights",
    "deactivate the light",
    "deactivate the lights",
    "deactivate relay",
    "disable light",
    "disable lights",
    # Expressive & nocturnal
    "lights out",
    "light out",
    "kill the light",
    "kill the lights",
    "cut the light",
    "cut the lights",
    "put off the light",
    "put off the lights",
    "put out the light",
    "put out the lights",
    "extinguish",
    "dark",
    "go dark",
    "pitch dark",
    "goodnight",
    "good night",
    "sleep mode",
    # Component specific
    "lamp off",
    "turn off lamp",
    "turn off the lamp",
    "strip off",
    "relay off",
    "led off",
    "green light off",
    # Vosk small model common phonetic misrecognitions
    "the north",
    "turn of",
    "turn ov",
    "to noff",
    "ten off",
    "torn off",
    "tune off",
    "term off",
)

# Token classification sets
ACTION_VERBS = {
    "turn",
    "switch",
    "power",
    "flip",
    "toggle",
    "put",
    "set",
    "make",
    "change",
    "hit",
}
TARGET_NOUNS = {
    "light",
    "lights",
    "lamp",
    "lamps",
    "relay",
    "strip",
    "led",
    "leds",
    "bulb",
    "illumination",
    "room",
    "it",
    "them",
}
NEGATION_WORDS = {"don't", "dont", "not", "never", "do not"}


def clean_text(text: str) -> str:
    """Normalize text by lowercasing, stripping punctuation, and collapsing whitespace."""
    lower = text.lower().strip()
    # Remove punctuation
    no_punct = lower.translate(str.maketrans("", "", string.punctuation))
    # Collapse whitespace
    return re.sub(r"\s+", " ", no_punct).strip()


def check_light_command(text: str) -> str:
    """Return ``ON``, ``OFF``, or ``UNKNOWN`` for a spoken light command.

    Supports:
    - Direct phrase matching against extensive synonym dictionaries
    - Natural language sentence structures with filler words
    - Phonetic aliases for common Vosk speech recognition variants
    - Flexible token intersection rules with negation guards
    """
    normalized = clean_text(text)
    if not normalized:
        return "UNKNOWN"

    # 1. Negation Check: Guard against "don't turn on", etc.
    words = normalized.split()
    word_set = set(words)
    has_negation = bool(NEGATION_WORDS & word_set)

    # 2. Check explicit phrase aliases
    for phrase in ON_PHRASES:
        if phrase in normalized:
            return "UNKNOWN" if has_negation else "ON"

    for phrase in OFF_PHRASES:
        if phrase in normalized:
            return "UNKNOWN" if has_negation else "OFF"

    if has_negation:
        return "UNKNOWN"

    # 3. Flexible Keyword Intersection Rules
    has_target = bool(TARGET_NOUNS & word_set)
    has_action = bool(ACTION_VERBS & word_set)

    # Turn/Switch/Power + ON + Target (e.g., "please turn the bedroom light on")
    if "on" in word_set:
        if has_target and has_action:
            return "ON"
        if has_action and ("it" in word_set or "them" in word_set):
            return "ON"
        if ("light" in word_set or "lights" in word_set) and len(words) <= 4:
            return "ON"

    # Turn/Switch/Power/Shut/Kill/Cut + OFF/OUT + Target
    if "off" in word_set or "out" in word_set:
        if has_target and (has_action or "shut" in word_set or "kill" in word_set or "cut" in word_set):
            return "OFF"
        if has_action and ("it" in word_set or "them" in word_set):
            return "OFF"
        if ("light" in word_set or "lights" in word_set) and len(words) <= 4:
            return "OFF"

    # 4. Standalone expressives
    if word_set & {"goodnight", "dark", "extinguish"}:
        return "OFF"
    if word_set & {"illuminate", "brighten"}:
        return "ON"

    return "UNKNOWN"


parse_command = check_light_command


def get_command_examples() -> Dict[str, List[Dict[str, str]]]:
    """Return categorized example voice commands with expected actions for documentation and UI."""
    return {
        "turn_on": [
            {"phrase": "turn on the light", "desc": "Standard voice command to activate the green LED and relay."},
            {"phrase": "lights on", "desc": "Short, direct command for quick activation."},
            {"phrase": "switch on the light", "desc": "Alternative action verb for light activation."},
            {"phrase": "power on the light", "desc": "Power command syntax for light control."},
            {"phrase": "put on the lights", "desc": "Colloquial phrase to turn on illumination."},
            {"phrase": "illuminate", "desc": "Single-word expressive command."},
            {"phrase": "turn it on", "desc": "Pronoun reference to the active light."},
            {"phrase": "activate relay", "desc": "Directly targets the 12V strip relay."},
            {"phrase": "can you turn on the lights please", "desc": "Polite conversational phrasing with filler words."},
        ],
        "turn_off": [
            {"phrase": "turn off the light", "desc": "Standard voice command to turn off light and open relay."},
            {"phrase": "lights off", "desc": "Short, direct command to cut illumination."},
            {"phrase": "switch off the light", "desc": "Alternative action verb for deactivation."},
            {"phrase": "power down", "desc": "Power syntax to deactivate all lighting circuits."},
            {"phrase": "shut off the lights", "desc": "Natural phrase to extinguish lights."},
            {"phrase": "lights out", "desc": "Everyday expressive phrase for bedtime/leaving."},
            {"phrase": "kill the lights", "desc": "Casual idiom to turn off illumination."},
            {"phrase": "goodnight", "desc": "Bedtime shortcut phrase to turn off light and relay."},
            {"phrase": "turn it off", "desc": "Pronoun reference to deactivate output."},
        ],
        "hardware_pins": [
            {"phrase": "Light ON (Pure Signal)", "desc": "Instant GPIO 22 & 23 HIGH signal via Quick Actions."},
            {"phrase": "Light OFF (Pure Signal)", "desc": "Instant GPIO 22 & 23 LOW signal via Quick Actions."},
            {"phrase": "Test Green LED", "desc": "Individual diagnostic toggle for BCM GPIO 22 (Pin 15)."},
            {"phrase": "Test 12V Relay", "desc": "Individual diagnostic toggle for BCM GPIO 23 (Pin 16)."},
            {"phrase": "Test Yellow Status LED", "desc": "Individual diagnostic toggle for BCM GPIO 27 (Pin 13)."},
            {"phrase": "Test Red Error LED", "desc": "Individual diagnostic toggle for BCM GPIO 17 (Pin 11)."},
        ],
        "tips": [
            {"title": "Hold-to-Talk (PTT)", "desc": "Press and hold the mic button or Spacebar while speaking. Release when done."},
            {"title": "Auto-Detect (Hands-Free)", "desc": "Tap the mic once to listen. Speak naturally; pause for 0.8s to auto-send."},
            {"title": "Sensitivity Tuning", "desc": "Adjust Speech Sensitivity in Settings if your room has background noise."},
            {"title": "Mobile Access (HTTPS)", "desc": "Launch with --ssl to allow microphone recording on iPhones and Android phones."},
        ]
    }
