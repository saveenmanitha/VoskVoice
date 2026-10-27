"""Dynamic LED and Actuator Controller for Raspberry Pi & Vosk Voice System.

Provides dynamic visual feedback across 3 LED channels:
- Green LED (GPIO 22): Dynamic confirmation burst on valid command recognition,
  then settles to target state (ON/OFF).
- Yellow LED (GPIO 27): Soft breathing fade for unknown/unrecognized commands,
  and rapid warning strobe for system, file, or decoding errors (rerouted from Red).
- Red LED (GPIO 17): Responsive recording/transmission tally light that pulses
  or blinks while audio is actively being recorded or sent by the client.

Supports real Raspberry Pi GPIO via gpiozero (PWMLED / LED) with automatic,
graceful fallback to thread-safe simulated hardware on Windows/Mac/Linux.
"""

import threading
import time
from typing import Callable, Optional


class SimulatedLED:
    """Thread-safe simulated LED for non-Raspberry Pi environments."""

    def __init__(self, pin: int, name: str = "SimulatedLED") -> None:
        self.pin = pin
        self.name = name
        self._is_lit = False
        self._value = 0.0
        self._lock = threading.Lock()
        self.last_animation: Optional[str] = None

    @property
    def is_lit(self) -> bool:
        with self._lock:
            return self._is_lit

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._is_lit

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    @value.setter
    def value(self, val: float) -> None:
        with self._lock:
            self._value = max(0.0, min(1.0, float(val)))
            self._is_lit = self._value > 0.05

    def on(self) -> None:
        with self._lock:
            self._is_lit = True
            self._value = 1.0

    def off(self) -> None:
        with self._lock:
            self._is_lit = False
            self._value = 0.0

    def toggle(self) -> None:
        with self._lock:
            self._is_lit = not self._is_lit
            self._value = 1.0 if self._is_lit else 0.0

    def close(self) -> None:
        self.off()

    def __repr__(self) -> str:
        return f"<SimulatedLED pin={self.pin} lit={self.is_lit}>"


class LEDController:
    """Manages dynamic animations and hardware states for Green, Yellow, and Red LEDs."""

    def __init__(
        self,
        green_pin: int = 22,
        yellow_pin: int = 27,
        red_pin: int = 17,
        force_simulation: bool = False,
    ) -> None:
        self.green_pin = green_pin
        self.yellow_pin = yellow_pin
        self.red_pin = red_pin
        self.is_simulation = force_simulation

        # Animation thread control flags
        self._active_threads: list[threading.Thread] = []
        self._recording_stop_event = threading.Event()
        self._recording_thread: Optional[threading.Thread] = None
        self._green_anim_stop = threading.Event()
        self._yellow_anim_stop = threading.Event()

        # Try initializing real gpiozero devices
        self.green = None
        self.yellow = None
        self.red = None
        self.has_pwm = False

        if not self.is_simulation:
            try:
                from gpiozero import LED, PWMLED
                try:
                    # Attempt PWM for yellow fade if available
                    self.yellow = PWMLED(yellow_pin)
                    self.has_pwm = True
                except Exception:
                    self.yellow = LED(yellow_pin)
                    self.has_pwm = False

                self.green = LED(green_pin)
                self.red = LED(red_pin)
                print(f"[HARDWARE] LEDController connected to GPIO Pins (Green:{green_pin}, Yellow:{yellow_pin}, Red:{red_pin})")
            except (ImportError, Exception) as err:
                # Graceful fallback to simulation
                self.is_simulation = True
                print(f"[INFO] Initializing simulated LEDController ({err})")

        if self.is_simulation:
            self.green = SimulatedLED(green_pin, "Green_LED")
            self.yellow = SimulatedLED(yellow_pin, "Yellow_LED")
            self.red = SimulatedLED(red_pin, "Red_LED")

        self.reset_all()

    # -------------------------------------------------------------------------
    # Core Primitive Operations
    # -------------------------------------------------------------------------

    def reset_all(self) -> None:
        """Immediately stop all background patterns and turn all LEDs OFF."""
        self._stop_recording_thread()
        self._green_anim_stop.set()
        self._yellow_anim_stop.set()
        time.sleep(0.02)
        self._green_anim_stop.clear()
        self._yellow_anim_stop.clear()

        try:
            self.green.off()
        except Exception:
            pass
        try:
            self.yellow.off()
        except Exception:
            pass
        try:
            self.red.off()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 1. Green LED: Dynamic Command Recognition Response
    # -------------------------------------------------------------------------

    def command_success(
        self,
        final_state: bool = True,
        pulses: int = 3,
        pulse_duration: float = 0.08,
        pause_duration: float = 0.07,
        blocking: bool = False,
    ) -> None:
        """Dynamic celebratory burst on valid command recognition.

        Blinks rapidly (e.g., 3 quick pulses) then transitions to final_state:
        - If final_state is True (Light turned ON): settles to ON.
        - If final_state is False (Light turned OFF): settles to OFF.
        """
        self._green_anim_stop.set()
        time.sleep(0.01)
        self._green_anim_stop.clear()

        def _run_dynamic_burst() -> None:
            if hasattr(self.green, "last_animation"):
                self.green.last_animation = "DYNAMIC_BLINK"
            for _ in range(pulses):
                if self._green_anim_stop.is_set():
                    break
                self.green.on()
                time.sleep(pulse_duration)
                self.green.off()
                time.sleep(pause_duration)

            if not self._green_anim_stop.is_set():
                if final_state:
                    self.green.on()
                else:
                    self.green.off()

        if blocking:
            _run_dynamic_burst()
        else:
            t = threading.Thread(target=_run_dynamic_burst, daemon=True)
            t.start()

    # -------------------------------------------------------------------------
    # 2. Yellow LED: Dynamic Fade on Unknown Command
    # -------------------------------------------------------------------------

    def command_unknown(
        self,
        cycles: int = 2,
        cycle_duration: float = 0.6,
        blocking: bool = False,
    ) -> None:
        """Smooth breathing fade on Yellow LED when command is unrecognized."""
        self._yellow_anim_stop.set()
        time.sleep(0.01)
        self._yellow_anim_stop.clear()

        def _run_fade() -> None:
            if hasattr(self.yellow, "last_animation"):
                self.yellow.last_animation = "BREATHING_FADE"

            steps = 15
            half_step = (cycle_duration / 2.0) / steps
            for _ in range(cycles):
                if self._yellow_anim_stop.is_set():
                    break
                # Fade in
                for s in range(1, steps + 1):
                    if self._yellow_anim_stop.is_set():
                        break
                    val = s / steps
                    if hasattr(self.yellow, "value"):
                        self.yellow.value = val
                    else:
                        if val > 0.5:
                            self.yellow.on()
                    time.sleep(half_step)

                # Fade out
                for s in range(steps, -1, -1):
                    if self._yellow_anim_stop.is_set():
                        break
                    val = s / steps
                    if hasattr(self.yellow, "value"):
                        self.yellow.value = val
                    else:
                        if val < 0.5:
                            self.yellow.off()
                    time.sleep(half_step)

            self.yellow.off()

        if blocking:
            _run_fade()
        else:
            t = threading.Thread(target=_run_fade, daemon=True)
            t.start()

    # -------------------------------------------------------------------------
    # 3. Yellow LED: Rapid Error Alert Strobe (Rerouted from Red LED)
    # -------------------------------------------------------------------------

    def system_error_alert(
        self,
        flashes: int = 5,
        flash_duration: float = 0.06,
        pause_duration: float = 0.06,
        blocking: bool = False,
    ) -> None:
        """Rapid warning strobe on Yellow LED to notify of file, audio, or system errors.

        Note: Errors are rerouted here from the Red LED so the Red LED remains
        dedicated exclusively to voice recording/transmission indication.
        """
        self._yellow_anim_stop.set()
        time.sleep(0.01)
        self._yellow_anim_stop.clear()

        def _run_rapid_strobe() -> None:
            if hasattr(self.yellow, "last_animation"):
                self.yellow.last_animation = "ERROR_ALERT_STROBE"
            for _ in range(flashes):
                if self._yellow_anim_stop.is_set():
                    break
                self.yellow.on()
                time.sleep(flash_duration)
                self.yellow.off()
                time.sleep(pause_duration)
            self.yellow.off()

        if blocking:
            _run_rapid_strobe()
        else:
            t = threading.Thread(target=_run_rapid_strobe, daemon=True)
            t.start()

    # -------------------------------------------------------------------------
    # 4. Red LED: Recording & Audio Transmission Tally Light
    # -------------------------------------------------------------------------

    def is_recording_active(self) -> bool:
        """Return True if the Red LED is currently in active recording blink mode."""
        return self._recording_thread is not None and self._recording_thread.is_alive()

    def start_recording(self, pulse_interval: float = 0.22) -> None:
        """Start dynamic tally-light blinking on Red LED while recording or sending voice."""
        if self.is_recording_active():
            return  # Already actively blinking

        self._recording_stop_event.clear()

        def _run_recording_blink() -> None:
            if hasattr(self.red, "last_animation"):
                self.red.last_animation = "RECORDING_PULSE"
            while not self._recording_stop_event.is_set():
                self.red.on()
                time.sleep(pulse_interval)
                if self._recording_stop_event.is_set():
                    break
                self.red.off()
                time.sleep(pulse_interval)
            self.red.off()

        self._recording_thread = threading.Thread(target=_run_recording_blink, daemon=True)
        self._recording_thread.start()

    def stop_recording(self) -> None:
        """Halt recording blink on Red LED and cleanly turn it OFF."""
        self._stop_recording_thread()
        try:
            self.red.off()
        except Exception:
            pass

    def _stop_recording_thread(self) -> None:
        if self._recording_thread and self._recording_thread.is_alive():
            self._recording_stop_event.set()
            self._recording_thread.join(timeout=0.6)
        self._recording_thread = None

    # -------------------------------------------------------------------------
    # Direct Control & Diagnostics Pin Tests
    # -------------------------------------------------------------------------

    def set_pin_direct(self, component: str, state: bool) -> str:
        """Diagnostic pin toggle bypass for manual testing."""
        comp = component.lower().strip()
        state_str = "ON" if state else "OFF"

        if comp in ("green", "light"):
            self._green_anim_stop.set()
            self.green.on() if state else self.green.off()
            return f"Green LED set to {state_str}"
        elif comp in ("yellow", "status"):
            self._yellow_anim_stop.set()
            self.yellow.on() if state else self.yellow.off()
            return f"Yellow LED set to {state_str}"
        elif comp in ("red", "rec", "recording"):
            if not state:
                self.stop_recording()
            else:
                self.red.on()
            return f"Red LED set to {state_str}"
        elif comp == "all":
            self.reset_all()
            if state:
                self.green.on()
                self.yellow.on()
                self.red.on()
            return f"All LEDs set to {state_str}"
        else:
            raise ValueError(f"Unknown LED component: {component}")

    def trigger_pattern_test(self, pattern: str) -> str:
        """Trigger a specific dynamic pattern test for diagnostics."""
        pat = pattern.lower().strip()
        if pat in ("green_dynamic", "green_blink", "command_success"):
            self.command_success(final_state=True)
            return "Triggered Green LED Dynamic Recognition Blink"
        elif pat in ("yellow_fade", "unknown_fade", "command_unknown"):
            self.command_unknown()
            return "Triggered Yellow LED Breathing Fade"
        elif pat in ("yellow_error", "rapid_error", "system_error_alert"):
            self.system_error_alert()
            return "Triggered Yellow LED Rapid Error Strobe (Rerouted Alert)"
        elif pat in ("red_recording_start", "rec_on"):
            self.start_recording()
            return "Started Red LED Recording Tally Blink"
        elif pat in ("red_recording_stop", "rec_off"):
            self.stop_recording()
            return "Stopped Red LED Recording Tally Blink"
        else:
            raise ValueError(f"Unknown pattern test: {pattern}")

    def get_status(self) -> dict[str, object]:
        """Return the current electrical/logical states of the LEDs."""
        green_active = getattr(self.green, "is_lit", False) or getattr(self.green, "is_active", False)
        yellow_active = getattr(self.yellow, "is_lit", False) or getattr(self.yellow, "is_active", False)
        red_active = getattr(self.red, "is_lit", False) or getattr(self.red, "is_active", False)
        return {
            "green_led_on": bool(green_active),
            "yellow_led_on": bool(yellow_active),
            "red_led_on": bool(red_active),
            "recording_active": self.is_recording_active(),
            "simulation": self.is_simulation,
        }

    def close(self) -> None:
        """Safely release all LED resources."""
        self.reset_all()
        if hasattr(self.green, "close"):
            self.green.close()
        if hasattr(self.yellow, "close"):
            self.yellow.close()
        if hasattr(self.red, "close"):
            self.red.close()
