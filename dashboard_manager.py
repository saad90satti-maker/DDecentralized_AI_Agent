#!/usr/bin/env python3
"""
manager.py — Resource Monitoring Dashboard Entry Point

Orchestrates the full monitoring pipeline:

  1. BufferMonitor (monitor.py) — zero-copy buffer inspection
  2. ProcessTracker (monitor.py) — psutil-based process enumeration
  3. SignalProcessor (processor.py) — FFT analysis and noise reduction

The pipeline runs on a configurable interval, collects system telemetry,
applies signal processing, and prints a structured dashboard report to
stdout. All errors are caught and logged; the main loop continues on
non-fatal failures.

Safe execution:
  - Graceful shutdown on SIGINT/SIGTERM via signal handlers
  - Each pipeline phase is wrapped in try/except with structured logging
  - Resource handles (buffer, file descriptors) are released on exit

Usage:
    python manager.py --interval 5 --top-processes 10
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
from pathlib import Path

import numpy as np

from monitor import BufferMonitor, ProcessTracker
from processor import SignalProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("manager")

# Global flag for graceful shutdown.
_running = True


def _handle_signal(signum, frame):
    """Signal handler for SIGINT/SIGTERM — sets the shutdown flag."""
    global _running
    signame = signal.Signals(signum).name
    logger.info("Received %s — shutting down gracefully...", signame)
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


class ResourceMonitor:
    """Top-level orchestrator for the monitoring dashboard.

    Binds together buffer inspection, process tracking, and optional
    signal processing into a single pipeline that runs on a timer.

    Parameters
    ----------
    interval : float
        Seconds between telemetry collection cycles.
    top_n : int
        Number of high-resource processes to display.
    enable_signal_processing : bool
        If True, run a simulated signal through the FFT pipeline and
        report SNR metrics.
    """

    def __init__(self, interval: float = 5.0, top_n: int = 5,
                 enable_signal_processing: bool = True):
        self.interval = interval
        self.top_n = top_n

        # Phase 1: Buffer monitor (zero-copy memory inspection)
        self.buffer_monitor = BufferMonitor(buffer_size=65536)

        # Phase 2: Process tracker (psutil)
        self.process_tracker = ProcessTracker(sort_by="cpu")

        # Phase 3: Signal processor (FFT-based noise reduction)
        self.signal_processor = (
            SignalProcessor(sample_rate=1000.0, window_size=1024, overlap=0.5)
            if enable_signal_processing else None
        )

        self._cycle_count = 0

    # ------------------------------------------------------------------
    # Pipeline phases
    # ------------------------------------------------------------------

    def _phase_buffer_inspection(self) -> dict:
        """Phase 1: read /proc/self/status via zero-copy buffer.

        Demonstrates memoryview + pread: the file is read directly into
        a pre-allocated bytearray, and a memoryview slice is returned
        without copying.

        Returns
        -------
        dict
            Keys: path, bytes_read, sample_lines
        """
        result = {"path": "/proc/self/status", "bytes_read": 0}
        data = self.buffer_monitor.read_region("/proc/self/status")
        if data is not None:
            result["bytes_read"] = data.nbytes
            # Decode first few lines for the dashboard.
            text = data.tobytes().decode("utf-8", errors="replace")
            lines = text.splitlines()[:5]
            result["sample_lines"] = lines
        return result

    def _phase_process_tracking(self) -> dict:
        """Phase 2: enumerate processes and I/O patterns.

        Returns
        -------
        dict
            Keys: total_processes, io_summary, top_processes
        """
        profiles = self.process_tracker.iter_profiles()
        io_summary = self.process_tracker.io_pattern_summary()
        top = self.process_tracker.high_resource_processes(self.top_n)
        return {
            "total_processes": len(profiles),
            "io_summary": io_summary,
            "top_processes": top,
        }

    def _phase_signal_processing(self) -> dict:
        """Phase 3: generate a synthetic noisy signal and apply FFT.

        Generates a 5-second signal consisting of a 50 Hz sine wave
        (the "signal") plus Gaussian noise. The FFT pipeline computes
        the spectrogram, estimates the noise floor, applies spectral
        gating, and measures the SNR before and after processing.

        Returns
        -------
        dict
            Keys: snr_before_db, snr_after_db, dominant_freq_hz,
                  noise_floor_db, gate_threshold_db
        """
        if self.signal_processor is None:
            return {"status": "disabled"}

        duration = 5.0  # seconds
        fs = self.signal_processor.sample_rate
        n = int(duration * fs)
        t = np.arange(n) / fs

        # Signal: 50 Hz sine wave
        signal = 0.5 * np.sin(2.0 * np.pi * 50.0 * t)
        # Noise: Gaussian with std = 0.2 (SNR ~ 8 dB before processing)
        noise = 0.2 * np.random.randn(n)
        noisy = signal + noise

        # Noise-only segment (first portion; ensure >= window_size)
        noise_len = max(int(0.5 * fs), self.signal_processor.window_size)
        noise_segment = noisy[:noise_len]

        # Estimate noise floor from the silent segment.
        noise_floor = self.signal_processor.estimate_noise_floor(
            noise_segment, percentile=10.0
        )

        # SNR before processing (using the noise segment as reference).
        # Pad noise_segment to match signal length for the comparison.
        noise_ref = np.pad(noise_segment, (0, max(0, len(signal) - len(noise_segment))),
                           mode='constant')[:len(signal)]
        snr_before = SignalProcessor.compute_snr(
            signal ** 2, noise_ref ** 2
        )

        # Apply spectral gating.
        cleaned = self.signal_processor.spectral_gate(
            noisy, noise_floor, threshold_db=3.0
        )

        # Estimate residual noise after gating.
        residual_noise = cleaned[:noise_len]
        noise_ref2 = np.pad(residual_noise, (0, max(0, len(signal) - len(residual_noise))),
                            mode='constant')[:len(signal)]
        snr_after = SignalProcessor.compute_snr(
            signal ** 2, noise_ref2 ** 2
        )

        # Dominant frequency in the cleaned signal (should be ~50 Hz).
        spectrum = self.signal_processor.compute_spectrum(cleaned)
        dominant_bin = int(np.argmax(spectrum))
        dominant_freq = self.signal_processor._freq_bins[dominant_bin]

        mean_noise_floor_db = float(np.mean(
            20.0 * np.log10(np.maximum(noise_floor, np.finfo(noise_floor.dtype).tiny))
        ))

        return {
            "snr_before_db": round(snr_before, 2),
            "snr_after_db": round(snr_after, 2),
            "snr_improvement_db": round(snr_after - snr_before, 2),
            "dominant_freq_hz": round(dominant_freq, 2),
            "noise_floor_db": round(mean_noise_floor_db, 2),
            "gate_threshold_db": 3.0,
        }

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run_forever(self):
        """Main orchestration loop — runs until interrupted.

        Each cycle executes the three pipeline phases and prints a
        structured dashboard report. Non-fatal errors in any phase
        are logged and the next cycle continues.
        """
        logger.info("ResourceMonitor starting (interval=%.1fs, top_n=%d)",
                     self.interval, self.top_n)
        logger.info("Pipeline phases: buffer_inspection -> process_tracking -> signal_processing")

        while _running:
            self._cycle_count += 1
            cycle_start = time.time()

            # ---- Phase 1 ----
            try:
                buffer_data = self._phase_buffer_inspection()
            except Exception as e:
                logger.error("Buffer inspection failed: %s", e)
                buffer_data = {"error": str(e)}

            # ---- Phase 2 ----
            try:
                proc_data = self._phase_process_tracking()
            except Exception as e:
                logger.error("Process tracking failed: %s", e)
                proc_data = {"error": str(e)}

            # ---- Phase 3 ----
            try:
                signal_data = self._phase_signal_processing()
            except Exception as e:
                logger.error("Signal processing failed: %s", e)
                signal_data = {"error": str(e)}

            # ---- Dashboard report ----
            elapsed = time.time() - cycle_start
            self._print_dashboard(buffer_data, proc_data, signal_data, elapsed)

            # Sleep for the remaining interval, checking _running periodically.
            sleep_until = cycle_start + self.interval
            while _running and time.time() < sleep_until:
                time.sleep(0.1)

    def _print_dashboard(self, buffer_data: dict, proc_data: dict,
                         signal_data: dict, elapsed: float):
        """Print a formatted dashboard to stdout."""
        sep = "-" * 68
        print(f"\n{sep}")
        print(f"  CYCLE #{self._cycle_count}  |  collect={elapsed:.2f}s  |  {time.strftime('%H:%M:%S')}")
        print(sep)

        # Buffer section
        buf = buffer_data
        print(f"  BUFFER:  {buf.get('path', 'N/A')}  |  {buf.get('bytes_read', 0)} bytes read")
        if "sample_lines" in buf:
            for line in buf["sample_lines"][:3]:
                print(f"    {line}")

        # Process section
        proc = proc_data
        print(f"  PROCESSES:  {proc.get('total_processes', 0)} total")
        io = proc.get("io_summary", {})
        if io:
            read_gb = io.get("total_read_bytes", 0) / (1024 ** 3)
            write_gb = io.get("total_write_bytes", 0) / (1024 ** 3)
            print(f"    I/O total:  {read_gb:.2f} GB read  |  {write_gb:.2f} GB written")
        top = proc.get("top_processes", [])
        if top:
            print(f"    Top {len(top)} by CPU:")
            print(f"    {'PID':>6}  {'NAME':<20}  {'CPU%':>6}  {'RSS MB':>8}  {'IO_RD MB':>10}  {'IO_WR MB':>10}")
            for p in top:
                rss_mb = p.get("memory_rss", 0) / (1024 ** 2)
                rd_mb = p.get("io_read_bytes", 0) / (1024 ** 2)
                wr_mb = p.get("io_write_bytes", 0) / (1024 ** 2)
                print(f"    {p['pid']:>6}  {p['name']:<20}  {p['cpu_percent']:>6.1f}  {rss_mb:>8.1f}  {rd_mb:>10.1f}  {wr_mb:>10.1f}")

        # Signal section
        sig = signal_data
        if sig and "snr_before_db" in sig:
            print(f"  SIGNAL PROCESSING (FFT):")
            print(f"    SNR before:  {sig['snr_before_db']:>6.2f} dB")
            print(f"    SNR after:   {sig['snr_after_db']:>6.2f} dB")
            print(f"    Improvement: {sig['snr_improvement_db']:>6.2f} dB")
            print(f"    Dominant Hz: {sig['dominant_freq_hz']:>6.1f}")
            print(f"    Noise floor: {sig['noise_floor_db']:>6.2f} dB")
        elif sig:
            print(f"  SIGNAL PROCESSING: {sig.get('status', 'N/A')}")

        print(sep)

    def shutdown(self):
        """Release all resources."""
        self.buffer_monitor.release()
        logger.info("Shutdown complete — released all resources")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resource Monitoring Dashboard — buffer, process, and FFT analysis",
    )
    parser.add_argument(
        "--interval", "-i", type=float, default=5.0,
        help="Collection interval in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--top-processes", "-n", type=int, default=5,
        help="Number of top processes to display (default: 5)",
    )
    parser.add_argument(
        "--no-signal", action="store_true",
        help="Disable FFT signal processing phase",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    """Entry point with full error handling and safe resource cleanup."""
    args = parse_args(argv)

    monitor = ResourceMonitor(
        interval=args.interval,
        top_n=args.top_processes,
        enable_signal_processing=not args.no_signal,
    )

    try:
        monitor.run_forever()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.critical("Unhandled error: %s", e, exc_info=True)
        return 1
    finally:
        monitor.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
