# Offline Voice-Controlled Light for Raspberry Pi

Control a green status LED and a 12 V DC light strip through a relay with spoken commands. Speech recognition
is performed locally with [Vosk](https://alphacephei.com/vosk/), so the project
does not need a cloud account or an internet connection after the software and
model have been installed.

This repository includes three ways to send a command:

1. **Pi microphone (recommended first setup):** the microphone, recognition
   model, and GPIO output all run on the Raspberry Pi.
2. **Laptop microphone over a local network:** the laptop records audio and the
   Pi performs recognition and controls the light.
3. **Browser interface:** a browser records audio and sends it to the same Pi
   server. This is the easiest option for users who do not want to install a
   microphone client on the laptop.

The project recognizes commands such as `turn on the light`, `turn off the
light`, `lights on`, `lights off`, `switch on`, and `switch off`.

## Contents

- [How the system works](#how-the-system-works)
- [Hardware](#hardware)
- [Hardware wiring](#hardware-wiring)
- [Software requirements](#software-requirements)
- [Installation on the Raspberry Pi](#installation-on-the-raspberry-pi)
- [Choose an operating mode](#choose-an-operating-mode)
- [Mode 1: Pi microphone](#mode-1-pi-microphone)
- [Mode 2: Laptop microphone over the network](#mode-2-laptop-microphone-over-the-network)
- [Mode 3: Browser interface](#mode-3-browser-interface)
- [Testing recorded WAV files](#testing-recorded-wav-files)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Safety](#safety)
- [Project layout](#project-layout)

## How the system works

```text
Microphone
   |
   v
16 kHz, mono, 16-bit PCM audio
   |
   v
Vosk speech recognition (runs locally)
   |
   v
Transcript -> command parser -> GPIO output
                                  |
                                  v
                              LED or relay
```

The command parser returns one of three results:

- `ON`: the configured light output is activated.
- `OFF`: the configured light output is deactivated.
- `UNKNOWN`: speech was detected, but it was not a supported light command.

The supplied small English model is suitable for a Raspberry Pi and is already
stored in `vosk-model-small-en-us-0.15/` in this repository. Vosk does not
send recorded audio to an online service.

## Hardware

### Required parts

| Part | Recommendation |
| --- | --- |
| Raspberry Pi | Pi 3B+, Pi 4, or Pi 5 |
| Power supply | The correct official or suitable supply for your Pi |
| Microphone | USB microphone or USB audio adapter |
| Output | A green LED with a 220-330 ohm resistor and a relay module suitable for the strip |
| Wiring | Breadboard and female-to-female/male-to-female jumper wires |

For the first test, use a single LED. Add a relay only after the software and
GPIO wiring have been verified.

### Optional network-mode hardware

Network and browser modes still need the Raspberry Pi, output circuit, and
power supply. The microphone can instead be connected to a laptop on the same
local network.

## Hardware wiring

The examples use **BCM GPIO numbering**, not physical pin numbers.

### Basic LED circuit

| LED circuit connection | Raspberry Pi |
| --- | --- |
| GPIO control wire | **GPIO 22**, physical pin 15 |
| GPIO 22 -> 220-330 ohm resistor -> LED anode (+, long leg) | In series |
| LED cathode (-, short leg) | Any Pi GND, for example physical pin 6 |

The resistor is required. Do **not** connect the green LED anode directly to
the Pi's 3.3 V pin if you want software control: that would leave it
permanently powered and bypass the GPIO logic. The GPIO drives the LED through
the resistor, and the cathode returns to Pi GND. Never connect an LED directly
between a GPIO pin and ground.

### Relay module circuit

| Relay pin | Raspberry Pi |
| --- | --- |
| `IN` / `SIG` | **GPIO 23**, physical pin 16 |
| `GND` | Pi GND, for example physical pin 6 |
| `VCC` | Module-rated supply, commonly 5 V from physical pin 2 or 4 |

The new `core/relay.py` `RelayModule` class owns relay on/off and cleanup
operations. Every supported ON command now turns on both GPIO 22 (green LED)
and GPIO 23 (relay); every supported OFF command turns both off. Some relay
boards are **active-low**: they switch on when the GPIO output is LOW. Use the
`--active-low` option for those boards. Check the relay board documentation
before connecting it.

### 12 V DC strip through the relay contacts

Use the relay contacts to switch the strip's separate 12 V supply. Do not
connect 12 V to any Raspberry Pi pin.

| Connection | Wiring |
| --- | --- |
| 12 V supply positive | Relay `COM` |
| Relay `NO` (normally open) | Strip positive (`+`) |
| Strip negative (`-`) | 12 V supply negative |
| Relay `NC` | Leave disconnected unless normally-on behavior is specifically required |

This keeps the strip off until the relay is energized. Confirm that the relay
contact voltage/current rating is greater than the strip's requirements, and
use an appropriate fuse and wire gauge for the strip.

The optional network server and recorded-file tester use a status LED on
**GPIO 27** (physical pin 13) by default. Connect that LED in the same way as
the first LED, with its own resistor. The recorded-file tester also uses GPIO
17 (physical pin 11) for its red error LED and GPIO 22 (physical pin 15) for
its green/light LED.

## Software requirements

- Raspberry Pi OS with Python 3.9 or newer
- A working USB microphone for local microphone mode
- A laptop and Raspberry Pi on the same LAN for network or browser mode
- Internet access only for the initial package/model download

The network server is intentionally a small HTTP service for a trusted home
LAN. It does not provide authentication or HTTPS encryption.

## Installation on the Raspberry Pi

Run these commands in a terminal on the Pi:

```bash
sudo apt update
sudo apt install -y git python3-pip python3-venv python3-dev \
    portaudio19-dev libasound2-dev unzip
```

Clone the project:

```bash
git clone https://github.com/saveenmanitha/Vosk_Project.git
cd Vosk_Project
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the Python packages used by the project:

```bash
python -m pip install --upgrade pip
python -m pip install vosk gpiozero sounddevice
```

### Install the Vosk model

The repository already contains `vosk-model-small-en-us-0.15/`. If that folder
is missing, download it from the Vosk model page:

```bash
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
rm vosk-model-small-en-us-0.15.zip
```

Confirm that the model directory contains folders such as `am`, `conf`,
`graph`, and `ivector`:

```text
Vosk_Project/
└── vosk-model-small-en-us-0.15/
    ├── am/
    ├── conf/
    ├── graph/
    └── ivector/
```

The command examples below assume the repository is located at
`/home/pi/Vosk_Project`. If it is somewhere else, pass the full path with
`--model`.

## Choose an operating mode

| Mode | Microphone location | Main command |
| --- | --- | --- |
| Pi microphone | Raspberry Pi | `python -m examples.live_microphone_controller` |
| Laptop Python client | Laptop | `python -m clients.network_voice_client ...` |
| Browser | Laptop/browser | Start the Pi server and open `clients/web` |

Start with **Mode 1** to verify the GPIO circuit. Use **Mode 2** or **Mode 3**
when the microphone must remain connected to a laptop.

## Mode 1: Pi microphone

Connect the USB microphone to the Pi and list the available audio devices:

```bash
python -m sounddevice
```

Start the controller:

```bash
cd /home/pi/Vosk_Project
python -m examples.live_microphone_controller
```

Run it from the project directory. This is important because `core` is a
project package. The controller also supports direct execution:

```bash
python examples/live_microphone_controller.py
```

Speak one of the supported commands:

```text
turn on the light
turn off the light
lights on
lights off
switch on
switch off
```

The default output is BCM GPIO 22. Choose another GPIO pin, microphone device,
or model with options:

```bash
python -m examples.live_microphone_controller \
    --model /home/pi/Vosk_Project/vosk-model-small-en-us-0.15 \
    --light-pin 22 \
    --device 2
```

For an active-low relay:

```bash
python -m examples.live_microphone_controller --active-low
```

Press `Ctrl+C` to stop. The program turns the output off and releases the GPIO
resource during shutdown.

## Mode 2: Laptop microphone over the network

In this mode, the Pi runs the Vosk model and controls the GPIO. The laptop
records a short command and sends a WAV file to the Pi over the local network.

### Start the server on the Pi

Find the Pi's local IP address:

```bash
hostname -I
```

Start the server from the project directory:

```bash
source .venv/bin/activate
python -m servers.network_voice_server
```

The server listens on all network interfaces at port `8765`. The default
hardware connections are:

- Green LED: BCM GPIO 22
- Relay input: BCM GPIO 23
- Yellow status LED: BCM GPIO 27

Useful server options:

```bash
python -m servers.network_voice_server \
    --model /home/pi/Vosk_Project/vosk-model-small-en-us-0.15 \
    --port 8765 \
    --light-pin 22 \
    --relay-pin 23 \
    --yellow-pin 27 \
    --active-low
```

Leave this terminal running.

### Run the Python client on the laptop

Install Python and `sounddevice` on the laptop. On Windows, run the following
in PowerShell; on Linux/macOS, use the equivalent Python commands:

```bash
python -m pip install sounddevice
```

From the repository folder on the laptop, replace the address below with the
Pi address:

```bash
python -m clients.network_voice_client \
    --server http://192.168.1.50:8765
```

The client waits for speech, detects approximately 0.8 seconds of silence,
creates a mono 16-bit WAV file, and uploads it. Press `Ctrl+C` to stop.

If the wrong microphone is selected, list devices and pass its number:

```bash
python -m sounddevice
python -m clients.network_voice_client \
    --server http://192.168.1.50:8765 \
    --device 2
```

## Mode 3: Browser interface

The browser interface uses the same Pi server as Mode 2. It requires a current
Chrome, Edge, or Firefox browser with microphone permission.

1. Start `servers.network_voice_server` on the Pi as described above.
2. On the laptop, open a second terminal in the project directory.
3. Serve the browser files instead of opening `index.html` directly:

   ```bash
   cd clients/web
   python -m http.server 8080
   ```

4. Open `http://localhost:8080` in the browser.
5. Enter the Pi URL, for example `http://192.168.1.50:8765`, and select
   **Connect**.
6. Allow microphone access, select **Start recording**, speak a command, and
   select **Stop recording**.

The page shows the transcript, action, response, green LED/strip state, relay
state, and yellow status-LED state. Serving the page from `localhost` is recommended because
browsers commonly block microphone access from a `file://` page or an
unsecured remote page.

The server exposes these endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/status` | Read the current light and status-LED state |
| `POST` | `/audio` | Submit a mono, 16-bit PCM WAV recording |

Do not expose port 8765 directly to the public internet. The service has no
login or encryption.

## Testing recorded WAV files

The `audio/` folder contains sample recordings. The audio must be mono,
16-bit PCM WAV; other formats are rejected by the transcriber.

To test one recording and display the result on the red, yellow, and green
LEDs:

```bash
python -m tests.audio_led_tester \
    /home/pi/Vosk_Project/audio/lights_on.wav \
    --model /home/pi/Vosk_Project/vosk-model-small-en-us-0.15
```

To process every WAV file in a folder:

```bash
python -m tests.audio_led_tester \
    --audio-folder /home/pi/Vosk_Project/audio \
    --model /home/pi/Vosk_Project/vosk-model-small-en-us-0.15
```

Use `--hold-delay 0` and `--inter-file-delay 0` for a faster test. The tester
uses GPIO 17 for errors, GPIO 27 for warnings/unrecognized speech, GPIO 22
for the green light state, and GPIO 23 for the relay. It turns the LEDs and
relay off when it exits.

For transcription-only development, inspect
`tests/voice_transcription_test.py` and `core/transcriber.py`; these do not
replace the GPIO safety checks in the runnable controller.

## Configuration

### GPIO and relay behavior

All GPIO arguments use BCM numbering:

```bash
python -m examples.live_microphone_controller --light-pin 22
python -m examples.live_microphone_controller --light-pin 22 --relay-pin 23
python -m servers.network_voice_server --light-pin 22 --relay-pin 23 --yellow-pin 27
```

Use `--active-low` only when the relay documentation says that LOW activates
the relay.

### Supported commands

The shared parser in `core/command_parser.py` accepts direct phrases including:

- `lights on`, `light on`, `turn on`, `turn on the light`, `switch on`
- `lights off`, `light off`, `turn off`, `turn off the light`, `switch off`

It also has a word-based fallback for combinations containing `turn` or
`switch`, `light` or `lights`, and `on` or `off`. Unrecognized speech is
ignored by the light controller.

### Audio format

The recognizer is configured for one audio channel, 16-bit samples, and a
16 kHz sample rate. The browser and laptop clients create this format
automatically. For a different microphone sample rate in local mode, pass
`--sample-rate`, but keep the input mono and 16-bit.

## Troubleshooting

### `sounddevice` cannot find a microphone

1. Confirm the USB microphone is connected.
2. Run `python -m sounddevice`.
3. Pass the correct device number with `--device N`.
4. On Linux, confirm that PortAudio and ALSA packages were installed.

### `Model path does not exist` or model loading fails

Run the command from the repository root or pass the complete model path:

```bash
python -m examples.live_microphone_controller \
    --model /home/pi/Vosk_Project/vosk-model-small-en-us-0.15
```

The path must be the extracted model directory, not the ZIP file.

### The transcript is empty or incorrect

Speak close to the microphone, reduce background noise, and use short,
natural commands. Confirm the recording is mono, 16-bit PCM WAV when testing
files. The small model is lightweight and may be less accurate than larger
Vosk models.

### The relay switches in the opposite direction

Stop the program and retry with `--active-low`. Do not repeatedly test an
unknown relay circuit while it is connected to mains power.

### The laptop cannot connect to the Pi

Confirm both devices are on the same LAN, verify the IP address with
`hostname -I`, and check that port `8765` is not blocked by the Pi firewall.
The server terminal should show a listening message. Try opening
`http://PI_IP_ADDRESS:8765/status` from the laptop; a JSON response means the
server is reachable.

### The browser cannot use the microphone

Use a current browser, open the page from `http://localhost:8080`, grant
microphone permission, and avoid opening the HTML file directly with
`file://`. If the page connects but recording fails, check the browser's site
permission settings.

## Safety

- Start with an LED before connecting a relay.
- Never drive a motor, lamp, or other load directly from a Raspberry Pi GPIO.
- Never connect mains voltage to a breadboard or exposed relay contacts.
- Use a properly enclosed, correctly rated relay module and follow local
  electrical regulations. If you are not qualified to work with mains wiring,
  ask a qualified electrician.
- Keep the Pi GPIO voltage within its limits and share a ground with the relay
  module where the module requires it.
- The programs turn outputs off during normal shutdown, but always disconnect
  power before changing wiring.
- The network server has no authentication or encryption; use it only on a
  trusted private network.

## Project layout

```text
Vosk_Project/
├── audio/                         # Sample WAV recordings
├── clients/
│   ├── network_voice_client.py    # Laptop microphone client
│   └── web/                       # Browser client
├── core/
│   ├── command_parser.py          # ON/OFF/UNKNOWN command parsing
│   └── transcriber.py             # WAV transcription helper
├── examples/
│   ├── live_microphone_controller.py
│   └── audio_file_light_controller.py
├── servers/
│   └── network_voice_server.py    # HTTP server for laptop/browser audio
├── tests/
│   ├── audio_led_tester.py       # WAV-to-LED test runner
│   └── voice_transcription_test.py
├── vosk-model-small-en-us-0.15/   # Local Vosk speech model
└── README.md
```

## License

See the repository license file if one is added to the project. The Vosk model
is distributed by Alpha Cephei under the terms provided with that model; check
its accompanying documentation before redistributing it.
