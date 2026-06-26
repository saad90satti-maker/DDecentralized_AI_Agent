#!/usr/bin/env python3
"""
dsp_manager.py -- DSP Pipeline Orchestrator

Entry point for the high-performance signal analysis pipeline. Links
the three modules:

  1. monitor.BufferMonitor    -- zero-copy buffer inspection / telemetry I/O
  2. monitor.ProcessTracker   -- psutil process enumeration & I/O profiling
  3. processor.SignalProcessor -- FFT analysis with adaptive noise gating

The orchestrator runs a continuous collection loop on a configurable
timer. Each cycle executes three phases:

  Phase 1 -- Buffer/Telemetry: read a /proc file (or hardware telemetry
             source) into the zero-copy memoryview buffer.
  Phase 2 -- Process Tracking: collect process CPU/memory/I/O profiles.
  Phase 3 -- Adaptive FFT: generate a synthetic test signal, estimate
             noise floor, apply spectral gating with parameters tuned
             by the AdaptiveFeedbackController to reach 21.17 dB SNR,
             and log the convergence trajectory.

Robust error handling:
  - Each phase is wrapped in try/except -- non-fatal failures are logged
    and the next cycle continues.
  - SIGINT/SIGTERM set a shutdown flag; the main loop exits cleanly and
    calls release() on all resources.
  - A persistent SNR log (CSV) is written to the filesystem for post-hoc
    analysis of controller convergence.

Extensions for hardware / satellite telemetry:
  Replace the synthetic test signal in Phase 3 with data from a
  TelemetryFrame source (e.g., SDR IQ samples via pyrtlsdr). The
  adaptive controller will automatically tune its parameters to the
  real channel conditions.

Usage:
    python dsp_manager.py --interval 3 --cycles 50
    python dsp_manager.py --interval 5 --no-fft   # process monitoring only
"""

import os
import sys
import csv
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
logger = logging.getLogger("dsp.manager")

# ---------------------------------------------------------------------------
# Global shutdown flag -- set by signal handler
# ---------------------------------------------------------------------------

_running = True


def _handle_signal(signum, frame):
    """Set the shutdown flag on SIGINT/SIGTERM for graceful teardown."""
    global _running
    signame = signal.Signals(signum).name
    logger.info("Received %s -- shutting down gracefully...", signame)
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# SNR Logger -- persistent CSV of adaptive feedback convergence
# ---------------------------------------------------------------------------

class SNRTracker:
    """Logs per-cycle SNR metrics to a CSV file for post-hoc analysis.

    The CSV columns track the adaptive feedback loop's convergence
    toward the target SNR (21.17 dB), including controller state
    (gate threshold, window exponent, integral term).

    Parameters
    ----------
    path : str or Path
        Output CSV path.
    """

    def __init__(self, path: str = "agent_logs/snr_convergence.csv"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._writer = None
        self._open()

    def _open(self):
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow([
            "cycle",
            "snr_before_db", "snr_after_db", "snr_improvement_db",
            "gate_threshold_db", "window_exponent",
            "snr_error_db", "integral_term",
            "cpu_pct", "memory_mb",
        ])
        self._file.flush()

    def write(self, cycle: int, snr_before: float, snr_after: float,
              gate_db: float, win_exp: float, error: float, integral: float,
              cpu_pct: float = 0.0, memory_mb: float = 0.0):
        if self._writer is None:
            return
        self._writer.writerow([
            cycle,
            round(snr_before, 2), round(snr_after, 2),
            round(snr_after - snr_before, 2),
            round(gate_db, 2), round(win_exp, 3),
            round(error, 2), round(integral, 3),
            round(cpu_pct, 1), round(memory_mb, 1),
        ])
        self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None
            self._writer = None
            logger.info("SNR log written to %s", self.path)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class DSPPipelineOrchestrator:
    """Top-level orchestrator linking buffer monitoring, process tracking,
    and adaptive FFT signal processing.

    Parameters
    ----------
    interval : float
        Seconds between collection cycles.
    top_n : int
        Number of top processes to display.
    enable_fft : bool
        Enable the adaptive FFT signal processing phase.
    target_snr : float
        Target SNR for the adaptive feedback controller (default 21.17 dB).
    max_cycles : int
        Maximum cycles before auto-shutdown (0 = unlimited).
    """

    def __init__(self, interval: float = 3.0, top_n: int = 5,
                 enable_fft: bool = True, target_snr: float = 21.17,
                 max_cycles: int = 0):
        self.interval = interval
        self.top_n = top_n
        self.max_cycles = max_cycles
        self.cycle_count = 0

        # Phase 1 -- Buffer monitor
        self.buffer_monitor = BufferMonitor(buffer_size=65536)

        # Phase 2 -- Process tracker
        self.process_tracker = ProcessTracker(sort_by="cpu")

        # Phase 3 -- Adaptive signal processor (target 21.17 dB)
        self.signal_processor = (
            SignalProcessor(
                sample_rate=1000.0,
                window_size=1024,
                overlap=0.5,
                adaptive=True,
                target_snr_db=target_snr,
            )
            if enable_fft else None
        )

        # SNR convergence logger
        self.snr_tracker = SNRTracker()

        logger.info("Orchestrator initialised: interval=%.1fs, top_n=%d, "
                     "fft=%s, target=%.2f dB, max_cycles=%d",
                     interval, top_n, enable_fft, target_snr, max_cycles)

    # ------------------------------------------------------------------
    # Phase 1 -- Buffer / Telemetry I/O
    # ------------------------------------------------------------------

    def _phase_buffer(self) -> dict:
        """Read /proc/self/status into the zero-copy memoryview buffer.

        On Linux this reads the process status file directly. On Windows
        it gracefully returns 0 bytes (no procfs). Extend by passing a
        TelemetryFrame source to read_from_telemetry() for SDR hardware.

        Returns
        -------
        dict
            path, bytes_read, read_count, total_bytes, sample_lines.
        """
        path = "/proc/self/status"
        data = self.buffer_monitor.read_region(path)
        if data is None:
            return {
                "path": path,
                "bytes_read": 0,
                "read_count": self.buffer_monitor.read_count,
                "total_bytes": self.buffer_monitor.total_bytes,
                "note": "procfs not available on this platform",
            }

        text = data.tobytes().decode("utf-8", errors="replace")
        return {
            "path": path,
            "bytes_read": data.nbytes,
            "read_count": self.buffer_monitor.read_count,
            "total_bytes": self.buffer_monitor.total_bytes,
            "sample_lines": text.splitlines()[:5],
        }

    # ------------------------------------------------------------------
    # Phase 2 -- Process tracking
    # ------------------------------------------------------------------

    def _phase_processes(self) -> dict:
        """Enumerate system processes and aggregate I/O.

        Returns
        -------
        dict
            total_processes, io_summary, top_processes.
        """
        profiles = self.process_tracker.collect()
        io_summary = self.process_tracker.io_summary()
        top = self.process_tracker.top_n(self.top_n)
        return {
            "total_processes": len(profiles),
            "io_summary": io_summary,
            "top_processes": top,
        }

    # ------------------------------------------------------------------
    # Phase 3 -- Adaptive FFT signal processing
    # ------------------------------------------------------------------

    def _phase_fft(self) -> dict:
        """Run one adaptive FFT processing cycle.

        Generates a 5-second synthetic test signal (50 Hz sine + Gaussian
        noise), applies the adaptive noise gate, and feeds the measured
        SNR to the AdaptiveFeedbackController which adjusts gate threshold
        and Hann window exponent toward the 21.17 dB target.

        Returns dict with SNR metrics and controller state.
        """
        if self.signal_processor is None:
            return {"status": "disabled"}

        fs = self.signal_processor.sample_rate
        duration = 5.0
        n = int(duration * fs)
        t = np.arange(n) / fs

        # Clean signal: 50 Hz sine
        signal_clean = 0.5 * np.sin(2.0 * np.pi * 50.0 * t)
        # Noise: Gaussian, std=0.2 -> ~8 dB SNR before processing
        noise = 0.2 * np.random.randn(n)
        noisy = signal_clean + noise

        # Noise segment (first portion; ensure >= window_size)
        wsize = self.signal_processor.window_size
        noise_len = max(int(0.5 * fs), wsize)
        noise_segment = noisy[:noise_len]

        # Run adaptive cycle
        result = self.signal_processor.process_adaptive(
            noisy_signal=noisy,
            noise_segment=noise_segment,
            signal_clean=signal_clean,
        )

        ctrl = result.get("controller_state", {})
        self.snr_tracker.write(
            cycle=self.cycle_count,
            snr_before=result["snr_before_db"],
            snr_after=result["snr_after_db"],
            gate_db=result["gate_threshold_used_db"],
            win_exp=result["window_exp_used"],
            error=ctrl.get("snr_error_db", 0.0),
            integral=ctrl.get("integral_term", 0.0),
        )

        return result

    # ------------------------------------------------------------------
    # Dashboard output
    # ------------------------------------------------------------------

    def _print_dashboard(self, buf: dict, proc: dict, fft: dict, elapsed: float):
        """Print a formatted dashboard report to stdout."""
        sep = "-" * 72
        print(f"\n{sep}")
        print(f"  CYCLE #{self.cycle_count}  |  {elapsed:.2f}s  |  {time.strftime('%H:%M:%S')}")
        print(f"  Target SNR: 21.17 dB  |  Adaptive: ON")
        print(sep)

        # Buffer
        print(f"  [BUFFER]  {buf.get('path', 'N/A')}")
        print(f"    Read: {buf.get('bytes_read', 0)} B  |  "
              f"Total I/O: {buf.get('total_bytes', 0) / 1024:.1f} KiB  |  "
              f"Reads: {buf.get('read_count', 0)}")

        # Processes
        procs = proc.get("total_processes", 0)
        io = proc.get("io_summary", {})
        rd_gb = io.get("total_read_bytes", 0) / (1024 ** 3)
        wr_gb = io.get("total_write_bytes", 0) / (1024 ** 3)
        print(f"  [PROCESSES]  {procs} tracked  |  "
              f"I/O: {rd_gb:.2f} GB read / {wr_gb:.2f} GB written")

        top = proc.get("top_processes", [])
        if top:
            print(f"    {'PID':>6}  {'NAME':<22}  {'CPU%':>6}  {'RSS MB':>8}  "
                  f"{'RD MB':>8}  {'WR MB':>8}")
            for p in top:
                rss = p.get("memory_rss", 0) / (1024 ** 2)
                rd = p.get("io_read_bytes", 0) / (1024 ** 2)
                wr = p.get("io_write_bytes", 0) / (1024 ** 2)
                print(f"    {p['pid']:>6}  {p['name']:<22}  {p['cpu_percent']:>6.1f}  "
                      f"{rss:>8.1f}  {rd:>8.1f}  {wr:>8.1f}")

        # FFT
        if fft and "snr_before_db" in fft:
            ctrl = fft.get("controller_state", {})
            print(f"  [FFT ADAPTIVE]")
            print(f"    SNR:     {fft['snr_before_db']:>6.2f} dB -> {fft['snr_after_db']:>6.2f} dB  "
                  f"(+{fft['snr_improvement_db']:.2f} dB)")
            print(f"    Target:  21.17 dB  |  Error: {ctrl.get('snr_error_db', 0):+.2f} dB")
            print(f"    Gate:    {fft['gate_threshold_used_db']:.1f} dB  |  "
                  f"Window: a={fft['window_exp_used']:.3f}  |  "
                  f"Integral: {ctrl.get('integral_term', 0):+.3f}")
            print(f"    Cycles:  {ctrl.get('cycle_count', 0)}  |  "
                  f"History: {len(self.signal_processor.snr_history)} pts")
        elif fft:
            print(f"  [FFT]  {fft.get('status', 'N/A')}")

        print(sep)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        """Run the orchestration loop until interrupted or max_cycles reached.

        Each cycle executes all three phases. Non-fatal errors in any
        phase are logged and the loop continues.
        """
        logger.info("Starting DSP pipeline (press Ctrl+C to stop)")

        while _running:
            self.cycle_count += 1
            if self.max_cycles > 0 and self.cycle_count > self.max_cycles:
                logger.info("Reached max_cycles=%d -- shutting down", self.max_cycles)
                break

            start = time.time()

            # Phase 1
            try:
                buf = self._phase_buffer()
            except Exception as e:
                logger.error("Phase 1 (buffer) failed: %s", e, exc_info=True)
                buf = {"error": str(e)}

            # Phase 2
            try:
                proc = self._phase_processes()
            except Exception as e:
                logger.error("Phase 2 (processes) failed: %s", e, exc_info=True)
                proc = {"error": str(e)}

            # Phase 3
            try:
                fft = self._phase_fft()
            except Exception as e:
                logger.error("Phase 3 (FFT) failed: %s", e, exc_info=True)
                fft = {"error": str(e)}

            elapsed = time.time() - start
            self._print_dashboard(buf, proc, fft, elapsed)

            # Sleep in small increments so we respond to SIGINT promptly
            deadline = start + self.interval
            while _running and time.time() < deadline:
                time.sleep(0.1)

    def shutdown(self):
        """Release all resources and close the SNR log."""
        self.buffer_monitor.release()
        self.snr_tracker.close()
        logger.info("Shutdown complete -- all resources released")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DSP Pipeline Orchestrator -- buffer/process monitoring + adaptive FFT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python dsp_manager.py --interval 5 --cycles 20 --target-snr 21.17\n"
            "  python dsp_manager.py --interval 2 --no-fft\n"
        ),
    )
    parser.add_argument("--interval", "-i", type=float, default=3.0,
                        help="Collection interval in seconds (default: 3.0)")
    parser.add_argument("--top-n", "-n", type=int, default=5,
                        help="Number of top processes (default: 5)")
    parser.add_argument("--no-fft", action="store_true",
                        help="Disable FFT signal processing phase")
    parser.add_argument("--target-snr", type=float, default=21.17,
                        help="Target SNR in dB for adaptive controller (default: 21.17)")
    parser.add_argument("--cycles", "-c", type=int, default=0,
                        help="Max cycles before auto-shutdown (0 = unlimited)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    orchestrator = DSPPipelineOrchestrator(
        interval=args.interval,
        top_n=args.top_n,
        enable_fft=not args.no_fft,
        target_snr=args.target_snr,
        max_cycles=args.cycles,
    )

    try:
        orchestrator.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.critical("Unhandled error: %s", e, exc_info=True)
        return 1
    finally:
        orchestrator.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
