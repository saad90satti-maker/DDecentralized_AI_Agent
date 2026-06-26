"""
processor.py — FFT-based signal analysis with adaptive noise gating.

Provides the mathematical optimisation layer for the signal analysis
pipeline. The core class, SignalProcessor, wraps numpy's rfft/irfft
routines to:

  - Transform time-domain data into the frequency domain
  - Apply spectral noise gating and band-pass filters
  - Reconstruct cleaned signals via overlap-add IFFT

Adaptive Feedback Loop (the key innovation):
  An AdaptiveFeedbackController monitors the output SNR after every
  processing cycle and adjusts two parameters in real time:

    1. Gate threshold (dB) — widened when SNR falls below target,
       tightened when SNR exceeds target, minimising unnecessary
       signal attenuation.
    2. Hann window shape exponent — the Hann window is raised to a
       power p ∈ [0.8, 2.0]. Higher exponents reduce sidelobe
       leakage at the cost of main-lobe broadening. The controller
       adjusts p to steer spectral resolution toward the target SNR.

  Target SNR: 21.17 dB (configurable). The controller converges
  via a proportional-integral (PI) law, ensuring stable tracking
  without oscillation.

  This design is extensible to hardware-in-the-loop scenarios
  (SDR, satellite demodulator, MEMS accelerometer) by replacing
  the synthetic test signal with a TelemetryFrame source.

Signal-to-Noise Ratio improvement strategies (documented):
  1. Spectral gating with adaptive threshold
  2. Band-pass filtering
  3. Adaptive window shaping
  4. Coherent averaging (periodic signals with trigger)
  5. Wiener / adaptive LMS filtering
  6. Wavelet thresholding (non-stationary transients)
  7. Matched filtering (known template)
"""

import numpy as np
import logging
from typing import Optional

logger = logging.getLogger("processor")


class AdaptiveFeedbackController:
    """Proportional-integral controller that drives SNR toward a target.

    Implements a discrete PI control law:

        e(t)  = SNR_target - SNR_measured(t)
        p(t)  = Kp * e(t)
        i(t) += Ki * e(t) * dt       (clamped to anti-windup limits)
        u(t)  = p(t) + i(t)

    The controller output u(t) is mapped to two actuator signals:

      - gate_threshold_offset: added to the base gate threshold (dB).
        Range: [-6, +12] dB. Positive values gate more aggressively.
      - window_exponent: power to raise the Hann window coefficients.
        Range: [0.8, 2.0]. Higher values reduce sidelobe leakage.

    Parameters
    ----------
    target_snr_db : float
        Desired SNR in dB (default 21.17).
    kp : float
        Proportional gain.
    ki : float
        Integral gain.
    dt : float
        Controller update interval in seconds.
    """

    def __init__(self, target_snr_db: float = 21.17,
                 kp: float = 0.15, ki: float = 0.05, dt: float = 3.0):
        self.target_snr_db = target_snr_db
        self.kp = kp
        self.ki = ki
        self.dt = dt

        self._integral = 0.0
        self._prev_error = 0.0
        self._gate_offset = 0.0
        self._window_exp = 1.0

        # Anti-windup limits
        self._integral_min = -10.0
        self._integral_max = 10.0

        # Actuator bounds
        self._gate_min = -6.0
        self._gate_max = 12.0
        self._win_min = 0.8
        self._win_max = 2.0

        self.cycle_count = 0
        logger.info("AdaptiveFeedbackController: target=%.2f dB, Kp=%.3f, Ki=%.3f",
                     target_snr_db, kp, ki)

    def update(self, snr_measured_db: float) -> dict:
        """Run one control cycle: measure error, compute actuation.

        Parameters
        ----------
        snr_measured_db : float
            SNR measured after the most recent processing cycle.

        Returns
        -------
        dict
            Keys: gate_threshold_db, window_exponent, snr_error_db,
                  integral_term, cycle_count.
        """
        self.cycle_count += 1

        # Error
        error = self.target_snr_db - snr_measured_db

        # PI control with trapezoidal integration
        self._integral += self.ki * error * self.dt
        self._integral = np.clip(self._integral, self._integral_min, self._integral_max)

        proportional = self.kp * error
        control = proportional + self._integral

        # Map control to actuators
        self._gate_offset = np.clip(control, self._gate_min, self._gate_max)
        self._window_exp = np.clip(
            1.0 - 0.3 * control / (abs(control) + 1e-6),
            self._win_min, self._win_max,
        )
        # Smooth the window exponent: map control [-10..+10] -> exponent [0.8..2.0]
        # Negative control (SNR too low) -> lower exponent (widen main lobe, let more signal through)
        # Positive control (SNR too high) -> raise exponent (narrow lobes, reduce noise leakage)
        self._window_exp = np.clip(
            1.4 - 0.06 * control,
            self._win_min, self._win_max,
        )

        self._prev_error = error

        return {
            "gate_threshold_db": round(self.base_threshold + self._gate_offset, 2),
            "window_exponent": round(self._window_exp, 3),
            "snr_error_db": round(error, 2),
            "integral_term": round(self._integral, 3),
            "cycle_count": self.cycle_count,
        }

    @property
    def gate_offset_db(self) -> float:
        return self._gate_offset

    @property
    def window_exponent(self) -> float:
        return self._window_exp

    @property
    def base_threshold(self) -> float:
        return 3.0  # default spectral gate threshold in dB

    def current_gate_threshold(self) -> float:
        """Full gate threshold = base + PI-adjusted offset."""
        return self.base_threshold + self._gate_offset

    def reset(self):
        """Reset integral term and actuators to neutral."""
        self._integral = 0.0
        self._gate_offset = 0.0
        self._window_exp = 1.0
        self.cycle_count = 0
        logger.debug("AdaptiveFeedbackController reset to neutral")


class SignalProcessor:
    """FFT-based signal analysis with adaptive noise reduction.

    Two operating modes:
      1. Fixed mode — uses static threshold and Hann window (legacy).
      2. Adaptive mode — uses AdaptiveFeedbackController to adjust
         gate threshold and window shape every cycle, targeting a
         configurable SNR (default 21.17 dB).

    Parameters
    ----------
    sample_rate : float
        Sampling rate in Hz.
    window_size : int
        FFT window length (power of two for optimal performance).
    overlap : float
        Overlap fraction [0, 1) for the sliding window.
    adaptive : bool
        Enable the adaptive feedback loop (default True).
    target_snr_db : float
        Target SNR for the adaptive controller (default 21.17).
    """

    def __init__(self, sample_rate: float = 1000.0,
                 window_size: int = 1024,
                 overlap: float = 0.5,
                 adaptive: bool = True,
                 target_snr_db: float = 21.17):
        self.sample_rate = sample_rate
        self.window_size = window_size
        self.overlap = overlap
        self._hop = int(window_size * (1.0 - overlap))

        # Base Hann window (exponent 1.0). Raised to *window_exp* each cycle
        # in adaptive mode.
        self._base_window = np.hanning(window_size)
        self._window = self._base_window.copy()
        self._window_exp_current = 1.0

        # Frequency bins (positive half of rfft)
        self._freq_bins = np.fft.rfftfreq(window_size, d=1.0 / sample_rate)

        # Adaptive controller
        self.adaptive = adaptive
        self.controller = AdaptiveFeedbackController(
            target_snr_db=target_snr_db,
            dt=3.0,
        ) if adaptive else None

        # SNR history for monitoring
        self.snr_history: list[float] = []
        self.gate_history: list[float] = []
        self.window_exp_history: list[float] = []

        logger.info("SignalProcessor initialised: %d-pt FFT @ %.0f Hz, overlap=%.2f, adaptive=%s",
                     window_size, sample_rate, overlap, adaptive)

    # ------------------------------------------------------------------
    # Adaptive window builder
    # ------------------------------------------------------------------

    def _build_window(self, exponent: float) -> np.ndarray:
        """Raise the base Hann window to *exponent*.

        Higher exponents suppress sidelobes at the cost of a wider
        main lobe — useful when the signal of interest is spectrally
        isolated and we want to reject broadband noise.

        The window is normalised so that the coherent gain (sum of
        window coefficients) remains constant, preserving absolute
        amplitude after the inverse FFT.
        """
        w = self._base_window ** exponent
        # Normalise to maintain unity coherent gain
        w *= self._base_window.sum() / w.sum()
        return w

    # ------------------------------------------------------------------
    # Core FFT pipeline
    # ------------------------------------------------------------------

    def compute_spectrum(self, samples: np.ndarray,
                         window_exp: float = 1.0) -> np.ndarray:
        """Compute the magnitude spectrum of a 1-D signal.

        Parameters
        ----------
        samples : np.ndarray, shape (N,)
        window_exp : float
            Hann window exponent (only used if adaptive=False).

        Returns
        -------
        np.ndarray, shape (window_size // 2 + 1,)
            Magnitude spectrum in dB.
        """
        if len(samples) < self.window_size:
            raise ValueError(
                f"Need >= {self.window_size} samples, got {len(samples)}"
            )

        window = self._build_window(window_exp) if window_exp != 1.0 else self._window
        frame = samples[:self.window_size] * window
        spectrum = np.fft.rfft(frame)
        mag = np.abs(spectrum)
        mag = np.maximum(mag, np.finfo(mag.dtype).tiny)
        return 20.0 * np.log10(mag)

    def compute_spectrogram(self, samples: np.ndarray) -> np.ndarray:
        """Compute a time-frequency spectrogram via overlapping frames.

        Parameters
        ----------
        samples : np.ndarray, shape (N,)

        Returns
        -------
        np.ndarray, shape (num_frames, window_size // 2 + 1)
        """
        num_frames = (len(samples) - self.window_size) // self._hop + 1
        if num_frames < 1:
            raise ValueError(
                f"Sample length {len(samples)} too short for {self.window_size}-pt window"
            )

        spectrogram = np.zeros(
            (num_frames, self.window_size // 2 + 1), dtype=np.float64
        )
        for i in range(num_frames):
            start = i * self._hop
            frame = samples[start:start + self.window_size] * self._window
            spectrum = np.fft.rfft(frame)
            mag = np.abs(spectrum)
            mag = np.maximum(mag, np.finfo(mag.dtype).tiny)
            spectrogram[i, :] = 20.0 * np.log10(mag)

        return spectrogram

    # ------------------------------------------------------------------
    # Noise estimation
    # ------------------------------------------------------------------

    def estimate_noise_floor(self, samples: np.ndarray,
                             percentile: float = 10.0) -> np.ndarray:
        """Estimate per-bin noise floor from a silent signal segment.

        Uses the *percentile* of magnitude values across all FFT frames
        as a robust noise estimate. The 10th percentile is standard —
        it excludes transient signal energy while capturing steady-state
        noise.

        Parameters
        ----------
        samples : np.ndarray
            Noise-only segment (e.g., first 0.5 s of an idle channel).
        percentile : float
            Percentile per frequency bin (default 10).

        Returns
        -------
        np.ndarray, shape (window_size // 2 + 1,)
            Noise magnitude per bin (linear scale).
        """
        if len(samples) < self.window_size:
            logger.warning("Noise segment too short (%d < %d), padding",
                           len(samples), self.window_size)
            samples = np.pad(samples, (0, self.window_size - len(samples)),
                             mode="reflect")

        num_frames = (len(samples) - self.window_size) // self._hop + 1
        if num_frames < 1:
            num_frames = 1
            self._hop = 1

        noise_mag = np.zeros(
            (num_frames, self.window_size // 2 + 1), dtype=np.float64
        )
        for i in range(num_frames):
            start = i * self._hop
            frame = samples[start:start + self.window_size] * self._window
            spectrum = np.fft.rfft(frame)
            noise_mag[i, :] = np.abs(spectrum)

        return np.percentile(noise_mag, percentile, axis=0)

    # ------------------------------------------------------------------
    # Spectral gating (noise reduction)
    # ------------------------------------------------------------------

    def spectral_gate(self, samples: np.ndarray,
                      noise_floor: np.ndarray,
                      gate_threshold_db: float = 3.0,
                      window_exp: float = 1.0) -> np.ndarray:
        """Apply spectral noise gating with adaptive window.

        How this improves SNR:
            Each frequency bin within *gate_threshold_db* of the noise
            floor is attenuated to zero. This removes low-level hiss
            and hum without affecting spectral peaks that carry signal.
            The gate is per-frame, per-bin, making it aware of non-
            stationary noise.

        Parameters
        ----------
        samples : np.ndarray
            Noisy time-domain signal.
        noise_floor : np.ndarray
            Per-bin noise magnitudes (linear) from estimate_noise_floor().
        gate_threshold_db : float
            Bins within this many dB of the noise floor are gated to zero.
        window_exp : float
            Hann window exponent for this cycle.

        Returns
        -------
        np.ndarray, shape (len(samples),)
            Cleaned signal after overlap-add reconstruction.
        """
        num_frames = (len(samples) - self.window_size) // self._hop + 1
        if num_frames < 1:
            raise ValueError(
                f"Sample length {len(samples)} < window size {self.window_size}"
            )

        # Build the window for this cycle
        window = self._build_window(window_exp) if window_exp != 1.0 else self._window

        # Convert noise floor to dB for comparison
        nf_safe = np.maximum(noise_floor, np.finfo(noise_floor.dtype).tiny)
        noise_db = 20.0 * np.log10(nf_safe)

        output = np.zeros(len(samples), dtype=np.float64)
        norm = np.zeros(len(samples), dtype=np.float64)

        for i in range(num_frames):
            start = i * self._hop
            frame = samples[start:start + self.window_size] * window
            spectrum = np.fft.rfft(frame)
            mag = np.abs(spectrum)
            mag_safe = np.maximum(mag, np.finfo(mag.dtype).tiny)
            mag_db = 20.0 * np.log10(mag_safe)

            # Gate: keep bins where (mag_db - noise_db) > gate_threshold_db
            mask = (mag_db - noise_db) > gate_threshold_db
            spectrum_filtered = spectrum * mask.astype(spectrum.dtype)

            frame_clean = np.fft.irfft(spectrum_filtered, n=self.window_size)
            output[start:start + self.window_size] += frame_clean * window
            norm[start:start + self.window_size] += window ** 2

        norm = np.maximum(norm, np.finfo(norm.dtype).tiny)
        output /= norm
        return output

    # ------------------------------------------------------------------
    # Band-pass filter
    # ------------------------------------------------------------------

    def band_pass_filter(self, samples: np.ndarray,
                         low_hz: float = 0.0,
                         high_hz: Optional[float] = None) -> np.ndarray:
        """Frequency-domain band-pass filter.

        Removes energy outside [low_hz, high_hz] by zeroing FFT bins.
        Theoretical SNR improvement is proportional to the fraction of
        the spectrum removed.

        Parameters
        ----------
        samples : np.ndarray
        low_hz : float
            Lower cutoff (default 0 = DC).
        high_hz : float, optional
            Upper cutoff (default Nyquist).

        Returns
        -------
        np.ndarray
        """
        if high_hz is None:
            high_hz = self.sample_rate / 2.0

        num_frames = (len(samples) - self.window_size) // self._hop + 1
        if num_frames < 1:
            raise ValueError(f"Sample length {len(samples)} < window size {self.window_size}")

        low_bin = int(low_hz / self._freq_bins[1]) if self._freq_bins[1] > 0 else 0
        high_bin = int(high_hz / self._freq_bins[1])

        output = np.zeros(len(samples), dtype=np.float64)
        norm = np.zeros(len(samples), dtype=np.float64)

        for i in range(num_frames):
            start = i * self._hop
            frame = samples[start:start + self.window_size] * self._window
            spectrum = np.fft.rfft(frame)

            spectrum[:low_bin] = 0.0
            spectrum[high_bin:] = 0.0

            frame_clean = np.fft.irfft(spectrum, n=self.window_size)
            output[start:start + self.window_size] += frame_clean * self._window
            norm[start:start + self.window_size] += self._window ** 2

        norm = np.maximum(norm, np.finfo(norm.dtype).tiny)
        output /= norm
        return output

    # ------------------------------------------------------------------
    # Adaptive processing cycle (one complete iteration)
    # ------------------------------------------------------------------

    def process_adaptive(self, noisy_signal: np.ndarray,
                         noise_segment: np.ndarray,
                         signal_clean: np.ndarray) -> dict:
        """Run one full adaptive processing cycle.

        Steps:
          1. Estimate noise floor from *noise_segment*.
          2. Compute SNR before processing (noisy vs. clean reference).
          3. Query AdaptiveFeedbackController for gate threshold + window exponent.
          4. Build the adapted window.
          5. Apply spectral gating with the adapted parameters.
          6. Compute SNR after processing.
          7. Feed post-SNR to the controller for next-cycle adaptation.
          8. Log history.

        Parameters
        ----------
        noisy_signal : np.ndarray
            The noisy input signal.
        noise_segment : np.ndarray
            Segment containing only noise (for floor estimation).
        signal_clean : np.ndarray
            Clean reference signal (for SNR computation).

        Returns
        -------
        dict
            Keys: cleaned, snr_before_db, snr_after_db, snr_improvement_db,
                  gate_threshold_used_db, window_exp_used, controller_state.
        """
        # 1. Estimate noise floor
        noise_floor = self.estimate_noise_floor(noise_segment, percentile=10.0)

        # 2. SNR before
        noise_ref = np.pad(noise_segment,
                           (0, max(0, len(signal_clean) - len(noise_segment))),
                           mode="constant")[:len(signal_clean)]
        snr_before = SignalProcessor.compute_snr(signal_clean ** 2, noise_ref ** 2)

        if self.controller is None:
            raise RuntimeError("Adaptive controller not initialised")

        # 3. Query controller for this cycle's parameters
        gate_db = self.controller.current_gate_threshold()
        win_exp = self.controller.window_exponent

        # 4. Build adapted window
        self._window = self._build_window(win_exp)
        self._window_exp_current = win_exp

        # 5. Apply spectral gating
        cleaned = self.spectral_gate(noisy_signal, noise_floor,
                                     gate_threshold_db=gate_db,
                                     window_exp=win_exp)

        # 6. SNR after
        residual_noise = cleaned[:len(noise_segment)]
        noise_ref2 = np.pad(residual_noise,
                            (0, max(0, len(signal_clean) - len(residual_noise))),
                            mode="constant")[:len(signal_clean)]
        snr_after = SignalProcessor.compute_snr(signal_clean ** 2, noise_ref2 ** 2)

        # 7. Feed back to controller
        ctrl_state = self.controller.update(snr_after)

        # 8. History
        self.snr_history.append(snr_after)
        self.gate_history.append(gate_db)
        self.window_exp_history.append(win_exp)

        return {
            "cleaned": cleaned,
            "snr_before_db": round(snr_before, 2),
            "snr_after_db": round(snr_after, 2),
            "snr_improvement_db": round(snr_after - snr_before, 2),
            "gate_threshold_used_db": round(gate_db, 2),
            "window_exp_used": round(win_exp, 3),
            "controller_state": ctrl_state,
        }

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def compute_snr(signal_power: np.ndarray,
                    noise_power: np.ndarray) -> float:
        """10 * log10(P_signal / P_noise).

        Parameters
        ----------
        signal_power : np.ndarray
            Power values for the signal region.
        noise_power : np.ndarray
            Power values for the noise-only region.

        Returns
        -------
        float
            SNR in dB. Inf if noise power is zero.
        """
        p_signal = float(np.mean(signal_power))
        p_noise = float(np.mean(noise_power))
        if p_noise <= 0.0:
            return float("inf")
        return 10.0 * np.log10(p_signal / p_noise)

    @property
    def nyquist_hz(self) -> float:
        return self.sample_rate / 2.0

    @property
    def bin_width_hz(self) -> float:
        return self.sample_rate / self.window_size
