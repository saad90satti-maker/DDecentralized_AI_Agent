"""
Modbus Protocol Module — Industrial device communication over Modbus TCP.
Read/write coils, discrete inputs, holding registers, and input registers
for PLCs, RTUs, sensors, and actuators.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ProtocolModbus")

try:
    from pymodbus.client import ModbusTcpClient
    from pymodbus.exceptions import ModbusException
    from pymodbus.pdu import ExceptionResponse
    HAS_MODBUS = True
except ImportError:
    HAS_MODBUS = False


class ModbusDevice:
    """
    Modbus TCP client for industrial device communication.

    Usage:
        device = ModbusDevice("192.168.1.100", 502)
        device.connect()
        holding = device.read_holding_registers(0, 10)
        device.write_single_coil(0, True)
        device.write_register(100, 75)
        device.disconnect()
    """

    def __init__(self, host: str, port: int = 502,
                 unit_id: int = 1, timeout: int = 10):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self._client = None
        self._connected = False
        self._device_info: Dict[str, Any] = {}

    def available(self) -> bool:
        return HAS_MODBUS

    def connect(self) -> bool:
        if not HAS_MODBUS:
            logger.warning("pymodbus not installed — install with: pip install pymodbus")
            return False

        try:
            self._client = ModbusTcpClient(
                self.host,
                port=self.port,
                timeout=self.timeout,
            )
            self._connected = self._client.connect()
            if self._connected:
                logger.info("Modbus connected: %s:%d (unit=%d)",
                            self.host, self.port, self.unit_id)
                self._probe_device()
            else:
                logger.warning("Modbus connection failed: %s:%d",
                               self.host, self.port)
            return self._connected
        except Exception as e:
            logger.warning("Modbus connect error: %s", e)
            return False

    def _probe_device(self) -> None:
        """Probe device identity if supported."""
        try:
            ident = self._client.read_device_information(
                read_code=0x01, unit=self.unit_id
            )
            if ident and not isinstance(ident, ExceptionResponse):
                self._device_info = {
                    "vendor": ident.vendor_name if hasattr(ident, "vendor_name") else "",
                    "product": ident.product_code if hasattr(ident, "product_code") else "",
                    "revision": ident.revision if hasattr(ident, "revision") else "",
                }
        except Exception:
            self._device_info = {"probed": False}

    # ---- Coils (digital outputs) ----

    def read_coils(self, address: int, count: int = 1) -> Optional[List[bool]]:
        if not self._ensure_connected():
            return None
        try:
            result = self._client.read_coils(address, count, unit=self.unit_id)
            if not isinstance(result, ExceptionResponse):
                return [result.bits[i] for i in range(count)]
            logger.warning("Modbus read_coils error response")
        except ModbusException as e:
            logger.warning("Modbus read_coils: %s", e)
        return None

    def write_single_coil(self, address: int, value: bool) -> bool:
        if not self._ensure_connected():
            return False
        try:
            result = self._client.write_coil(address, value, unit=self.unit_id)
            ok = not isinstance(result, ExceptionResponse)
            logger.debug("Modbus write coil %d=%s: %s", address, value, "OK" if ok else "FAIL")
            return ok
        except ModbusException as e:
            logger.warning("Modbus write_coil: %s", e)
            return False

    # ---- Discrete inputs (digital inputs) ----

    def read_discrete_inputs(self, address: int, count: int = 1) -> Optional[List[bool]]:
        if not self._ensure_connected():
            return None
        try:
            result = self._client.read_discrete_inputs(address, count, unit=self.unit_id)
            if not isinstance(result, ExceptionResponse):
                return [result.bits[i] for i in range(count)]
        except ModbusException as e:
            logger.warning("Modbus read_discrete_inputs: %s", e)
        return None

    # ---- Holding registers (read/write) ----

    def read_holding_registers(self, address: int, count: int = 1) -> Optional[List[int]]:
        if not self._ensure_connected():
            return None
        try:
            result = self._client.read_holding_registers(address, count, unit=self.unit_id)
            if not isinstance(result, ExceptionResponse):
                return result.registers
        except ModbusException as e:
            logger.warning("Modbus read_holding_registers: %s", e)
        return None

    def write_single_register(self, address: int, value: int) -> bool:
        if not self._ensure_connected():
            return False
        try:
            result = self._client.write_register(address, value, unit=self.unit_id)
            ok = not isinstance(result, ExceptionResponse)
            logger.debug("Modbus write register %d=%d: %s", address, value, "OK" if ok else "FAIL")
            return ok
        except ModbusException as e:
            logger.warning("Modbus write_register: %s", e)
            return False

    def write_registers(self, address: int, values: List[int]) -> bool:
        if not self._ensure_connected():
            return False
        try:
            result = self._client.write_registers(address, values, unit=self.unit_id)
            ok = not isinstance(result, ExceptionResponse)
            return ok
        except ModbusException as e:
            logger.warning("Modbus write_registers: %s", e)
            return False

    # ---- Input registers (read-only) ----

    def read_input_registers(self, address: int, count: int = 1) -> Optional[List[int]]:
        if not self._ensure_connected():
            return None
        try:
            result = self._client.read_input_registers(address, count, unit=self.unit_id)
            if not isinstance(result, ExceptionResponse):
                return result.registers
        except ModbusException as e:
            logger.warning("Modbus read_input_registers: %s", e)
        return None

    # ---- Convenience: read sensor values as scaled floats ----

    def read_scaled_sensor(self, register_address: int,
                           scale: float = 1.0, offset: float = 0.0) -> Optional[float]:
        raw = self.read_input_registers(register_address, 1)
        if raw:
            return raw[0] * scale + offset
        return None

    # ---- Connection management ----

    def _ensure_connected(self) -> bool:
        if not self._connected or not self._client:
            return self.connect()
        return True

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._connected = False
            logger.info("Modbus disconnected: %s:%d", self.host, self.port)

    def scan_range(self, start: int = 0, end: int = 100) -> Dict[str, List[int]]:
        """Scan a range of holding registers and return non-zero values."""
        results = {}
        for addr in range(start, end, 10):
            count = min(10, end - addr)
            values = self.read_holding_registers(addr, count)
            if values and any(v != 0 for v in values):
                results[f"HR_{addr}_{addr+count-1}"] = values
        return results

    @property
    def is_connected(self) -> bool:
        return self._connected

    def status(self) -> Dict[str, Any]:
        return {
            "protocol": "Modbus TCP",
            "connected": self._connected,
            "host": f"{self.host}:{self.port}",
            "unit_id": self.unit_id,
            "device_info": self._device_info,
        }


class ModbusSensorArray:
    """High-level array of Modbus sensors for factory telemetry."""

    def __init__(self):
        self._devices: Dict[str, ModbusDevice] = {}
        self._mappings: Dict[str, Dict[str, Any]] = {}

    def add_device(self, name: str, device: ModbusDevice) -> None:
        self._devices[name] = device

    def add_sensor_mapping(self, sensor_id: str, device_name: str,
                           register_type: str, address: int,
                           scale: float = 1.0, offset: float = 0.0) -> None:
        self._mappings[sensor_id] = {
            "device": device_name,
            "register_type": register_type,
            "address": address,
            "scale": scale,
            "offset": offset,
        }

    def read_all(self) -> Dict[str, Any]:
        results = {}
        for sensor_id, mapping in self._mappings.items():
            device = self._devices.get(mapping["device"])
            if not device:
                results[sensor_id] = {"error": "device not found"}
                continue
            if not device.is_connected:
                device.connect()

            try:
                reg_type = mapping["register_type"]
                addr = mapping["address"]
                if reg_type == "holding":
                    val = device.read_holding_registers(addr, 1)
                elif reg_type == "input":
                    val = device.read_input_registers(addr, 1)
                elif reg_type == "coil":
                    val = device.read_coils(addr, 1)
                elif reg_type == "discrete":
                    val = device.read_discrete_inputs(addr, 1)
                else:
                    val = None

                if val:
                    raw = val[0] if isinstance(val, list) else val
                    scaled = raw * mapping["scale"] + mapping["offset"]
                    results[sensor_id] = {
                        "raw": raw, "scaled": scaled,
                        "unit": mapping.get("unit", ""),
                    }
                else:
                    results[sensor_id] = {"error": "no data"}
            except Exception as e:
                results[sensor_id] = {"error": str(e)}

        return results

    def connect_all(self) -> Dict[str, bool]:
        status = {}
        for name, device in self._devices.items():
            status[name] = device.connect()
        return status

    def disconnect_all(self) -> None:
        for device in self._devices.values():
            device.disconnect()
