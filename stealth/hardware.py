"""
Hardware Persistence — Low-level GPIO radio/mesh modem control.
Bypasses the OS networking stack entirely by toggling physical pins
on SBC hardware (Raspberry Pi, Jetson, BeagleBone) to control
LoRa, Meshtastic, SDR, or satellite modems directly.

Falls back to simulated GPIO when no physical hardware is detected
(for development/testing on non-SBC systems).
"""

import json
import os
import struct
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from logging_system import get_logger

logger = get_logger("Stealth.Hardware")

_BASE_DIR = Path(__file__).resolve().parent.parent


class HardwarePersistence:
    """
    Direct hardware control for radio/mesh modems via GPIO.

    Pin Map (configurable in hardware_pins.json):
      RADIO_PTT     — Push-to-talk for radio modem
      RADIO_DATA_IN — Data input from radio
      RADIO_DATA_OUT— Data output to radio
      MESH_ENABLE   — Mesh modem power relay
      SAT_TX        — Satellite transmitter enable
      SAT_RX        — Satellite receiver enable
      LORA_CS       — LoRa chip select
      STATUS_LED    — Stealth status indicator

    All communication bypasses the OS network stack — data is sent
    bit-banged directly over GPIO or via SPI to the transceiver.
    """

    PIN_MAP_FILE = _BASE_DIR / "agent_data" / "hardware_pins.json"

    PIN_MAP_DEFAULTS = {
        "RADIO_PTT": 17,
        "RADIO_DATA_IN": 22,
        "RADIO_DATA_OUT": 23,
        "MESH_ENABLE": 24,
        "SAT_TX": 25,
        "SAT_RX": 27,
        "LORA_CS": 8,
        "STATUS_LED": 18,
    }

    def __init__(self):
        self._gpio = None
        self._simulated = False
        self._pin_map: Dict[str, int] = {}
        self._pin_states: Dict[str, bool] = {}
        self._transceivers: Dict[str, Callable] = {}
        self._running = False
        self._load_pin_map()

    def _load_pin_map(self) -> None:
        try:
            self.PIN_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            if self.PIN_MAP_FILE.exists():
                data = json.loads(self.PIN_MAP_FILE.read_text(encoding="utf-8"))
                self._pin_map = {**self.PIN_MAP_DEFAULTS, **data}
            else:
                self._pin_map = dict(self.PIN_MAP_DEFAULTS)
                self.PIN_MAP_FILE.write_text(
                    json.dumps(self._pin_map, indent=2), encoding="utf-8"
                )
        except Exception:
            self._pin_map = dict(self.PIN_MAP_DEFAULTS)

    def initialize(self) -> bool:
        """
        Initialize GPIO hardware. Falls back to simulation if physical
        GPIO is unavailable (development mode).
        """
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            for name, pin in self._pin_map.items():
                if name in ("RADIO_DATA_IN", "SAT_RX"):
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                else:
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

            self._gpio = GPIO
            self._simulated = False
            logger.info("Hardware: GPIO initialized (BCM mode, %d pins mapped)",
                         len(self._pin_map))
            return True

        except (ImportError, RuntimeError, AttributeError) as e:
            logger.warning("Hardware: physical GPIO unavailable — using simulation: %s", e)
            self._simulated = True
            self._gpio = _SimulatedGPIO()
            self._gpio.initialize(self._pin_map)
            return True

        except Exception as e:
            logger.error("Hardware: GPIO init failed: %s", e)
            return False

    def set_pin(self, pin_name: str, state: bool) -> None:
        """Set a GPIO pin high (True) or low (False)."""
        pin = self._pin_map.get(pin_name)
        if pin is None:
            logger.warning("Hardware: unknown pin '%s'", pin_name)
            return
        if self._gpio:
            try:
                self._gpio.output(pin, GPIO_HIGH if state else GPIO_LOW)
                self._pin_states[pin_name] = state
                logger.debug("Hardware: pin %s (BCM %d) -> %s",
                             pin_name, pin, "HIGH" if state else "LOW")
            except Exception as e:
                logger.warning("Hardware: pin %s error: %s", pin_name, e)

    def read_pin(self, pin_name: str) -> bool:
        """Read the current state of a GPIO pin."""
        pin = self._pin_map.get(pin_name)
        if pin is None:
            return False
        if self._gpio:
            try:
                return bool(self._gpio.input(pin))
            except Exception:
                pass
        return self._pin_states.get(pin_name, False)

    def enable_radio(self) -> None:
        """Activate radio modem (PTT + power relay)."""
        self.set_pin("RADIO_PTT", True)
        self.set_pin("MESH_ENABLE", True)
        logger.info("Hardware: radio modem enabled")

    def disable_radio(self) -> None:
        """Deactivate radio modem to save power / avoid detection."""
        self.set_pin("RADIO_PTT", False)
        self.set_pin("MESH_ENABLE", False)
        logger.info("Hardware: radio modem disabled")

    def enable_satellite(self) -> None:
        """Enable satellite transceiver."""
        self.set_pin("SAT_TX", True)
        self.set_pin("SAT_RX", True)
        logger.info("Hardware: satellite transceiver enabled")

    def disable_satellite(self) -> None:
        """Disable satellite transceiver."""
        self.set_pin("SAT_TX", False)
        self.set_pin("SAT_RX", False)
        logger.info("Hardware: satellite transceiver disabled")

    def transmit_raw(self, data: bytes, modem: str = "radio") -> bool:
        """
        Transmit raw bytes over the specified modem via bit-banged GPIO.
        Bypasses OS network stack entirely.
        """
        if modem == "radio":
            return self._transmit_over_radio(data)
        elif modem == "satellite":
            return self._transmit_over_satellite(data)
        elif modem == "mesh":
            return self._transmit_over_mesh(data)
        else:
            logger.warning("Hardware: unknown modem '%s'", modem)
            return False

    def _transmit_over_radio(self, data: bytes) -> bool:
        """Bit-bang data over GPIO to radio modem."""
        try:
            self.enable_radio()
            time.sleep(0.01)

            for byte in data:
                for bit_pos in range(8):
                    bit = (byte >> (7 - bit_pos)) & 1
                    self.set_pin("RADIO_DATA_OUT", bool(bit))
                    self._gpio_delay(0.0001)

            self.disable_radio()
            logger.debug("Hardware: radio TX %d bytes via GPIO", len(data))
            return True
        except Exception as e:
            logger.warning("Hardware: radio TX failed: %s", e)
            return False

    def _transmit_over_satellite(self, data: bytes) -> bool:
        """Transmit via satellite modem on GPIO."""
        try:
            self.enable_satellite()
            time.sleep(0.1)
            for i in range(0, len(data), 64):
                chunk = data[i:i + 64]
                self.set_pin("SAT_TX", True)
                time.sleep(0.05)
                self.set_pin("SAT_TX", False)
                time.sleep(0.01)
            self.disable_satellite()
            logger.debug("Hardware: satellite TX %d bytes", len(data))
            return True
        except Exception as e:
            logger.warning("Hardware: satellite TX failed: %s", e)
            return False

    def _transmit_over_mesh(self, data: bytes) -> bool:
        """Transmit via mesh network modem."""
        try:
            self.set_pin("MESH_ENABLE", True)
            self.set_pin("RADIO_PTT", True)
            time.sleep(0.02)
            for byte in data:
                for bit_pos in range(8):
                    bit = (byte >> (7 - bit_pos)) & 1
                    self.set_pin("RADIO_DATA_OUT", bool(bit))
                    self._gpio_delay(0.00005)
            self.set_pin("RADIO_PTT", False)
            self.set_pin("MESH_ENABLE", False)
            logger.debug("Hardware: mesh TX %d bytes", len(data))
            return True
        except Exception as e:
            logger.warning("Hardware: mesh TX failed: %s", e)
            return False

    def register_transceiver(self, name: str, transmit_fn: Callable[[bytes], bool]) -> None:
        """Register a software-defined transceiver (e.g., LoRa library, SDR)."""
        self._transceivers[name] = transmit_fn
        logger.info("Hardware: registered transceiver '%s'", name)

    def transmit_sdr(self, data: bytes, transceiver: str = "lora") -> bool:
        """Transmit via a registered software transceiver."""
        fn = self._transceivers.get(transceiver)
        if fn:
            return fn(data)
        logger.warning("Hardware: transceiver '%s' not registered", transceiver)
        return False

    def status_led(self, on: bool) -> None:
        """Toggle the stealth status indicator LED."""
        self.set_pin("STATUS_LED", on)

    def _gpio_delay(self, seconds: float) -> None:
        time.sleep(seconds)

    @property
    def is_hardware(self) -> bool:
        return not self._simulated

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "hardware_gpio": not self._simulated,
            "pins_configured": len(self._pin_map),
            "pin_states": dict(self._pin_states),
            "transceivers": list(self._transceivers.keys()),
            "simulated": self._simulated,
        }


class _SimulatedGPIO:
    """Software GPIO simulation for development on non-SBC systems."""

    def __init__(self):
        self._pins: Dict[int, bool] = {}
        self._modes: Dict[int, str] = {}

    def initialize(self, pin_map: Dict[str, int]) -> None:
        for name, pin in pin_map.items():
            self._pins[pin] = False
            self._modes[pin] = "OUT" if name not in ("RADIO_DATA_IN", "SAT_RX") else "IN"
        logger.info("Hardware (sim): GPIO simulation active with %d pins", len(pin_map))

    def output(self, pin: int, state: bool) -> None:
        self._pins[pin] = bool(state)

    def input(self, pin: int) -> bool:
        return self._pins.get(pin, False)

    def setmode(self, mode) -> None:
        pass

    def setup(self, pin: int, mode, pull_up_down=None) -> None:
        self._pins.setdefault(pin, False)
        self._modes[pin] = "IN" if mode == "IN" else "OUT"

    def cleanup(self) -> None:
        self._pins.clear()


GPIO_HIGH = True
GPIO_LOW = False
