# 🚀 Release v1.0.0 — Offline Voice-Controlled Smart Lighting & Dual-Server System

Welcome to the **v1.0.0** initial release of the **Offline Voice-Controlled Smart Light & Appliance Controller** for Raspberry Pi!

This release introduces an end-to-end, privacy-focused smart home system featuring a **distributed dual-server architecture**:
1. 🍓 **Raspberry Pi Voice Detection Server Scripts** (`servers/voice_detection_server.py`)
2. 🌐 **Client Web Server Implementation** (`clients/client_web_server.py` & `clients/web/`)

---

## 🌟 What's Included in This Release

### 1. 🍓 Raspberry Pi Voice Detection Server
The backend microservice runs locally on the Raspberry Pi, delivering fast, 100% offline speech recognition and GPIO hardware control:

- **100% Offline Kaldi Speech Engine:** Employs the Vosk speech engine to transcribe 16 kHz Mono WAV audio locally on the Pi with zero telemetry or cloud latency.
- **Dynamic Model Auto-Discovery:** `core/model_resolver.py` scans standard directories (`./vosk-model*`, `../`, `~/.cache/vosk/`) so the server starts without needing hardcoded model paths.
- **Phonetic Synonym & Alias Parser:** `core/command_parser.py` maps natural spoken variations (`"turn on the lights"`, `"switch off"`, `"lamp on"`, `"light on"`) to deterministic hardware actions.
- **Comprehensive Hardware & LED Feedback:**
  - **12V Relay (BCM 23):** Safely switches high-power 12V LED strips or appliances.
  - **Green LED (BCM 22):** Dynamic multi-blink acknowledgement burst upon valid command execution.
  - **Yellow Status LED (BCM 27):** Soft breathing fade on unknown speech and rapid strobe alert on audio errors.
  - **Red Recording Tally (BCM 17):** Pulsing studio tally light while client devices are recording.
- **Unified Multi-Client LAN Logging:** Captures genuine originating client IP addresses (`X-Forwarded-For` / `X-Real-IP`) and provides queryable `/status`, `/history`, and `/control` REST endpoints.
- **High-Performance Threading:** Powered by `ThreadedVoiceServer` with `TCP_NODELAY` and non-blocking DNS resolution.

### 2. 🌐 Web Client Server Implementation
The frontend client bridges any browser (desktop, tablet, or smartphone) to the Raspberry Pi:

- **Zero External Dependencies:** Built entirely with Python 3's standard library (`http.server`, `urllib.request`, `ssl`). Requires no `pip install` on client PCs!
- **Glassmorphic Web Interface (`clients/web/index.html`):**
  - **Live Audio Waveform:** Real-time Web Audio API visualizer displaying voice frequency bars and amplitude changes.
  - **Dual Voice Input Modes:** Push-to-Talk (click-and-hold or `[Space]` key) and Hands-Free Auto-Detect with automatic Voice Activity Detection (VAD) silence cutoff.
  - **Instant GPIO Quick Actions:** Direct bypass buttons (`Light ON` / `Light OFF`) to control lights instantly without STT overhead.
  - **Live Hardware State HUD:** Real-time status indicators reflecting physical relay and LED states.
  - **Multi-Device Activity Feed:** Live history feed tracking timestamps, transcribed speech, recognized commands, and client IP addresses.
- **Mobile HTTPS & Self-Signed SSL:** Includes an integrated SSL launcher (`--ssl`) allowing Safari (iOS) and Chrome (Android) on local Wi-Fi to grant microphone permissions.
- **Built-in Mock Pi Mode:** Run `python clients/client_web_server.py --mock-pi` to test the entire dashboard without needing a physical Raspberry Pi.

### 3. 🛠️ Hardware Diagnostics Suite & Launchers
- **Diagnostics Dashboard (`/diagnostics.html`):** Test individual pins (`GPIO 22`, `23`, `27`, `17`), execute 500ms flash pulses, and invoke master overrides (`Turn All ON` / `Turn All OFF`).
- **Interactive Windows Launcher (`start_web_client.bat`):** Double-click menu to launch HTTP, HTTPS, or Mock mode without terminal commands.
- **Bash Launchers:** `start_voice_server.sh` and `start_web_client.sh` for seamless Linux/macOS execution.

---

## ⚡ Quick Start for Users

### Step A: Raspberry Pi Setup (Voice Server)
```bash
# 1. Clone repository
git clone https://github.com/saveenmanitha/Vosk_Project.git
cd Vosk_Project

# 2. Install dependencies
pip3 install vosk gpiozero

# 3. Start the Voice Server
python3 servers/voice_detection_server.py
# Or use the launcher script:
./start_voice_server.sh
```

### Step B: Client Machine Setup (Web Server)
On your PC, Laptop, or Mac (Python 3.9+ only; no pip dependencies needed):

```bash
# Windows: Double-click start_web_client.bat OR run:
python clients/client_web_server.py --pi http://<RASPBERRY_PI_IP>:8765

# For Mobile Phone access over HTTPS:
python clients/client_web_server.py --pi http://<RASPBERRY_PI_IP>:8765 --ssl

# For Testing without physical hardware:
python clients/client_web_server.py --mock-pi
```

Open your browser to:
- **HTTP:** `http://localhost:8080` (or `http://<YOUR_PC_IP>:8080`)
- **HTTPS:** `https://<YOUR_PC_IP>:8443`
- **Diagnostics:** `http://localhost:8080/diagnostics.html`

---

## 🧪 Verification & Testing
Run the automated test suite directly from the workspace:
```bash
python -m unittest discover tests
```
Both `test_voice_commands.py` and `test_web_server.py` execute automatically with mock hardware drivers.

