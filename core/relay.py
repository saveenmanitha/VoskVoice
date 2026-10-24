"""Reusable GPIO relay control for the Raspberry Pi."""


class RelayModule:
    """Control a relay module connected to one Raspberry Pi GPIO pin."""

    def __init__(self, pin: int, active_low: bool = False) -> None:
        try:
            from gpiozero import OutputDevice
        except ImportError as error:
            raise RuntimeError(
                "gpiozero is required for relay control. "
                "Install it on the Raspberry Pi with: pip3 install gpiozero"
            ) from error

        self.pin = pin
        self.device = OutputDevice(
            pin,
            active_high= False,
            initial_value=False,
        )

    @property
    def is_on(self) -> bool:
        """Return whether the relay is currently energized."""
        return self.device.is_active

    def on(self) -> None:
        """Energize the relay."""
        self.device.on()

    def off(self) -> None:
        """De-energize the relay."""
        self.device.off()

    def close(self) -> None:
        """Turn the relay off and release its GPIO resource."""
        self.off()
        self.device.close()
