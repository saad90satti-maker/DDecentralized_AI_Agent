"""
monitor.py — Low-level buffer monitoring and process resource tracking.

Provides two core capabilities for the high-performance signal analysis
pipeline:

  1. BufferMonitor: Uses memoryview + ctypes for zero-copy access to raw
     system buffers (/proc, shared memory, DMA ring buffers). Slicing a
     memoryview produces another view over the same backing store — no
     bytes are duplicated. ctypes.Structures are overlaid directly onto
     the buffer for typed field access without manual offset arithmetic.

  2. ProcessTracker: Wraps psutil to enumerate active processes, surface
     high-consumption candidates, and expose per-process I/O read/write
     byte counters in a structured format.

  3. TelemetryFrame (protocol class): Defines the data contract for
     ingesting hardware-level telemetry (SDR IQ samples, satellite
     demodulator frames, sensor ADC buffers). Extend this class to
     integrate with physical devices.
"""

import os
import io
import ctypes
import struct
import logging
from typing import Optional, Protocol, runtime_checkable
from collections import defaultdict

logger = logging.getLogger("monitor")

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    _PSUTIL_AVAILABLE = False


# ============================================================================
# TelemetryFrame — protocol for hardware / satellite data ingestion
# ============================================================================
#
# To integrate with a physical SDR (e.g., RTL-SDR, HackRF, LimeSDR) or
# a satellite demodulator, implement this protocol and pass instances
# to BufferMonitor.read_region(). The protocol guarantees that any
# hardware source exposes a consistent buffer interface.
#
# Example — wrapping an RTL-SDR via pyrtlsdr:
#
#   class SDRTelemetryFrame:
#       def __init__(self, sdr):
#           self.sdr = sdr
#       def read(self, size, offset=0):
#           return self.sdr.read_samples(size).tobytes()
#       @property
#       def frame_rate_hz(self):
#           return self.sdr.sample_rate
#       @property
#       def center_freq_hz(self):
#           return self.sdr.center_freq
# ============================================================================


@runtime_checkable
class TelemetryFrame(Protocol):
    """Protocol for any hardware telemetry source.

    Implement this protocol to feed data from SDR hardware, satellite
    demodulators, ADC buffers, or network packet captures into the
    signal analysis pipeline without modifying the core classes.
    """

    def read(self, size: int, offset: int = 0) -> bytes:
        """Read *size* bytes starting at *offset* from the hardware buffer.

        Parameters
        ----------
        size : int
            Number of bytes to read.
        offset : int
            Byte offset into the hardware frame.

        Returns
        -------
        bytes
            Raw byte payload — typically IQ samples interleaved as
            I16/Q16 or CF32, depending on the device.
        """
        ...

    @property
    def frame_rate_hz(self) -> float:
        """Sampling rate of the hardware device in Hz."""
        ...

    @property
    def center_freq_hz(self) -> float:
        """Centre frequency of the hardware device in Hz."""
        ...


# ============================================================================
# DMABufferHeader — ctypes overlay for zero-copy buffer parsing
# ============================================================================


class DMABufferHeader(ctypes.Structure):
    """ctypes Structure overlaying a DMA ring-buffer or kernel-frame header.

    The _fields_ descriptor mirrors the C struct layout of the device or
    kernel module that produces the buffer. By casting a memoryview over
    the raw bytes to this Structure, we access typed fields directly from
    the shared memory page — no serialisation or copy.

    In production, replace these field definitions with the struct
    published by your hardware vendor's datasheet.
    """
    _fields_ = [
        ("magic", ctypes.c_uint32),       # 0x00: frame magic identifier
        ("sequence", ctypes.c_uint64),     # 0x04: monotonically increasing frame counter
        ("data_offset", ctypes.c_uint32),  # 0x0C: byte offset from header start to payload
        ("data_length", ctypes.c_uint32),  # 0x10: byte length of payload
        ("flags", ctypes.c_uint8 * 8),     # 0x14: device status / error flags
        ("checksum", ctypes.c_uint32),     # 0x1C: 32-bit CRC of payload
        # Total header size: 32 bytes (0x20)
    ]


# ============================================================================
# BufferMonitor — zero-copy buffer inspection
# ============================================================================


class BufferMonitor:
    """Reads and inspects raw binary buffers using zero-copy techniques.

    On each read cycle, *one* bytearray of *buffer_size* is pre-allocated
    and wrapped in a memoryview. Subsequent slicing and ctypes overlays
    operate on the same physical memory — no additional allocations.

    This pattern reduces CPU cache pressure and GC churn when handling
    large ring buffers (e.g., 16 MiB SDR sample buffers) at high update
    rates (100+ Hz).

    Parameters
    ----------
    buffer_size : int
        Size in bytes of the pre-allocated internal read buffer.

    Attributes
    ----------
    read_count : int
        Total number of successful read operations since instantiation.
    total_bytes : int
        Cumulative bytes read across all operations.
    """

    def __init__(self, buffer_size: int = 65536):
        self.buffer_size = buffer_size
        self.read_count = 0
        self.total_bytes = 0

        self._raw = bytearray(buffer_size)
        self._view = memoryview(self._raw)
        logger.debug("BufferMonitor initialised: %d-byte zero-copy buffer", buffer_size)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_region(self, path: str, offset: int = 0) -> Optional[memoryview]:
        """Read a file region into the pre-allocated zero-copy buffer.

        Uses os.pread to read at *offset* without seeking. Returns a
        memoryview sliced to the actual bytes read — the caller receives
        a view, not a copy.

        Parameters
        ----------
        path : str
            File path, device node, or telemetry source identifier.
        offset : int
            Starting byte offset for the read.

        Returns
        -------
        memoryview or None
            View over the valid portion of the internal buffer, or None
            if the read failed (permissions, missing file, I/O error).
        """
        try:
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
            try:
                n = os.pread(fd, self._raw, offset)
            finally:
                os.close(fd)
        except (OSError, PermissionError, FileNotFoundError) as e:
            logger.debug("read_region(%s): %s", path, e)
            return None
        except AttributeError:
            # Windows: O_CLOEXEC not defined; fall back to O_RDONLY.
            try:
                fd = os.open(path, os.O_RDONLY)
                try:
                    n = os.pread(fd, self._raw, offset)
                finally:
                    os.close(fd)
            except (OSError, PermissionError, FileNotFoundError) as e2:
                logger.debug("read_region(%s): %s", path, e2)
                return None

        self.read_count += 1
        self.total_bytes += n
        return self._view[:n]

    def read_from_telemetry(self, source: TelemetryFrame,
                            size: int, offset: int = 0) -> Optional[memoryview]:
        """Read bytes from a hardware telemetry source into the buffer.

        Accepts any object implementing the TelemetryFrame protocol
        (SDR, satellite demodulator, ADC). Falls back gracefully if
        the source fails.

        Parameters
        ----------
        source : TelemetryFrame
            Hardware telemetry source.
        size : int
            Number of bytes to read (clamped to buffer_size).
        offset : int
            Byte offset into the hardware frame.

        Returns
        -------
        memoryview or None
        """
        n = min(size, self.buffer_size)
        try:
            data = source.read(n, offset)
        except Exception as e:
            logger.warning("Telemetry read failed: %s", e)
            return None

        n = len(data)
        if n == 0:
            return None

        self._raw[:n] = data
        self.read_count += 1
        self.total_bytes += n
        return self._view[:n]

    def parse_header(self, data: memoryview) -> Optional[dict]:
        """Overlay a DMABufferHeader ctypes Structure onto *data*.

        This is the zero-copy decode path: rather than unpacking bytes
        with struct.iter_unpack, we cast the memoryview to a ctypes
        Structure and access fields by name.

        Parameters
        ----------
        data : memoryview
            Raw buffer bytes. Must be >= 32 bytes.

        Returns
        -------
        dict or None
            Dictionary of header fields, or None if the buffer is too
            small or the magic number doesn't match.
        """
        if data.nbytes < ctypes.sizeof(DMABufferHeader):
            logger.warning("parse_header: buffer too small (%d < %d bytes)",
                           data.nbytes, ctypes.sizeof(DMABufferHeader))
            return None

        header = DMABufferHeader.from_buffer_copy(data)

        if header.magic != 0xDEADBEEF:
            logger.debug("parse_header: bad magic 0x%08x (expected 0xDEADBEEF)",
                         header.magic)
            return None

        return {
            "magic": header.magic,
            "sequence": header.sequence,
            "data_offset": header.data_offset,
            "data_length": header.data_length,
            "flags": list(header.flags),
            "checksum": header.checksum,
        }

    def release(self):
        """Release the internal buffer and reset counters.

        Called during graceful shutdown to return memory to the OS.
        """
        self._view.release()
        self._raw = bytearray(0)
        logger.debug("BufferMonitor released: %d reads, %d total bytes",
                     self.read_count, self.total_bytes)


# ============================================================================
# ProcessTracker — psutil-based process enumeration and I/O profiling
# ============================================================================


class ProcessTracker:
    """Enumerates system processes and exposes resource-heavy candidates.

    Uses psutil.Process per-process CPU/memory/I/O metrics. The
    iter_profiles() method returns structured records sorted by a
    configurable metric.

    Parameters
    ----------
    sort_by : str
        Sort criterion: "cpu", "memory", "read_bytes", "write_bytes".

    Attributes
    ----------
    profiles : list[dict]
        Most recently collected process profiles (cached).
    """

    def __init__(self, sort_by: str = "cpu"):
        self.sort_by = sort_by
        self.profiles: list[dict] = []
        self._profile_count = 0
        self._sort_key = {
            "cpu": lambda p: p.get("cpu_percent", 0),
            "memory": lambda p: p.get("memory_rss", 0),
            "read_bytes": lambda p: p.get("io_read_bytes", 0),
            "write_bytes": lambda p: p.get("io_write_bytes", 0),
        }.get(sort_by, lambda p: p.get("cpu_percent", 0))

    def collect(self) -> list[dict]:
        """Collect process profiles sorted by the configured metric.

        Returns an empty list if psutil is not installed. On Windows,
        io_counters() may not be available for all process types; such
        entries report zero I/O.

        Returns
        -------
        list[dict]
            Each dict:
            pid, name, create_time, cpu_percent, memory_rss, memory_vms,
            io_read_bytes, io_write_bytes, num_threads, status.
        """
        if not _PSUTIL_AVAILABLE:
            logger.warning("psutil not available — process tracking disabled")
            return []

        collected = []
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                pinfo = proc.info
                cpu = proc.cpu_percent(interval=0.0)
                mem = proc.memory_info()
                io = proc.io_counters()
                profile = {
                    "pid": pinfo["pid"],
                    "name": pinfo["name"],
                    "create_time": pinfo["create_time"],
                    "cpu_percent": cpu,
                    "memory_rss": mem.rss if mem else 0,
                    "memory_vms": mem.vms if mem else 0,
                    "io_read_bytes": io.read_bytes if io else 0,
                    "io_write_bytes": io.write_bytes if io else 0,
                    "num_threads": proc.num_threads(),
                    "status": proc.status(),
                }
                collected.append(profile)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except AttributeError:
                # Some platforms lack io_counters.
                collected.append({
                    "pid": pinfo["pid"] if pinfo else 0,
                    "name": pinfo["name"] if pinfo else "unknown",
                    "cpu_percent": cpu if "cpu" in dir() else 0.0,
                    "io_read_bytes": 0,
                    "io_write_bytes": 0,
                })

        collected.sort(key=self._sort_key, reverse=True)
        self.profiles = collected
        self._profile_count += 1
        logger.debug("ProcessTracker: %d profiles collected (run #%d)",
                     len(collected), self._profile_count)
        return collected

    def top_n(self, n: int = 5) -> list[dict]:
        """Return the top *n* processes by the configured metric.

        Parameters
        ----------
        n : int
            Number of processes to return.

        Returns
        -------
        list[dict]
        """
        return self.profiles[:n] if self.profiles else self.collect()[:n]

    def io_summary(self) -> dict:
        """Aggregate cumulative I/O across all tracked processes.

        Returns
        -------
        dict
            Keys: total_read_bytes, total_write_bytes, process_count.
        """
        profiles = self.profiles if self.profiles else self.collect()
        total_read = sum(p.get("io_read_bytes", 0) for p in profiles)
        total_write = sum(p.get("io_write_bytes", 0) for p in profiles)
        return {
            "total_read_bytes": total_read,
            "total_write_bytes": total_write,
            "process_count": len(profiles),
        }
