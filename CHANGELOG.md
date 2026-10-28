# Changelog

All notable changes to the **Offline Voice-Controlled Light & Appliance System** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-28

### Initial Production Release

This milestone release introduces a dual-server distributed architecture designed for 100% offline, private, and latency-optimized voice automation.

#### 🎙️ Raspberry Pi Voice Server (`servers/voice_detection_server.py`)
- **Vosk Kaldi Speech Recognition Engine:** Fully offline English STT processing 16 kHz Mono PCM WAV audio without external cloud calls.
- **Phonetic Command Matcher (`core/command_parser.py`):** Multi-synonym and alias recognition for commands like `"light on"`, `"lights on"`, `"switch off"`, `"turn on the lights"`.
- **Dynamic Model Auto-Discovery (`core/model_resolver.py`):** Automatically locates Vosk Kaldi speech models across workspace, parent directories, and user home folders.
- **Hardware Actuation & LED Visual Feedback (`core/led_controller.py`, `core/relay.py`):**
  - Optocoupled 12V relay switching on BCM 23.
  - Green confirmation LED on BCM 22 with dynamic multi-burst acknowledgement.
  - Yellow status/error LED on BCM 27 with breathing fade for unknown speech and rapid warning strobing for audio errors.
  - Red tally LED on BCM 17 with rhythmic pulse indicating microphone recording in progress.
- **Multi-Device Client Activity Tracking:** HTTP logging tracking originating client IP addresses (`X-Forwarded-For`, `X-Real-IP`, and socket IP) with history endpoints (`/status`, `/history`, `/control`, `/gpio`, `/recording`).
- **Threaded HTTP Server:** Multi-threaded request handler with `TCP_NODELAY` and fast non-blocking IP resolution.

#### 🌐 Web Client Server Implementation (`clients/client_web_server.py`)
- **Zero-Dependency Architecture:** Built completely on Python 3 standard library (`http.server`, `urllib`, `ssl`) without requiring third-party pip dependencies.
- **Glassmorphic Modern UI (`clients/web/`):**
  - **Live Audio Waveform:** HTML5 Canvas visualizer rendering real-time mic amplitude and frequency bars.
  - **Flexible Recording Modes:** Push-to-Talk (button hold & spacebar trigger) and Hands-Free Auto-Detect with Voice Activity Detection (VAD) silence cutoff.
  - **Instant GPIO Quick Action Bypasses:** Hardware override buttons (`Light ON` / `Light OFF`) providing immediate control without STT processing.
  - **Live Hardware HUD:** Polling status of all LEDs and relay pins.
  - **Multi-Device Activity Feed:** Live feed of timestamped voice transcriptions, parsed commands, and client device IPs, plus a clear log button.
- **Built-in Mobile HTTPS Reverse Proxy:** Generates self-signed SSL certificates (`--ssl`) allowing mobile devices (iOS Safari, Android Chrome) to access microphone streams over LAN.
- **Integrated Mock Pi Mode:** Full offline simulation of hardware states and history for development without physical Raspberry Pi hardware.

#### 🛠️ Diagnostics & Tooling Suite
- **Hardware Diagnostics Page (`clients/web/diagnostics.html`):** Interactive testing suite allowing individual pin toggles, 500ms flash pulses, and master overrides (`Turn All ON` / `Turn All OFF`).
- **Cross-Platform Launchers:**
  - `start_voice_server.sh`: Bash launcher for the Raspberry Pi backend.
  - `start_web_client.bat`: Interactive Windows launcher with mode menu (HTTP, HTTPS, Mock).
  - `start_web_client.sh`: Linux/macOS launcher for the client web server.
- **Automated Test Suite (`tests/`):**
  - `tests/test_voice_commands.py`: Audio transcription and command parsing verification.
  - `tests/test_web_server.py`: Reverse proxy, client IP forwarding, and concurrency verification.

