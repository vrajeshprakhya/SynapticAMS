"""
Error Detector / Eye Monitor — SerDes RX Adaptation Block

Measures the quality of the received data stream using three complementary
metrics that feed the LMS adaptive engine:

  1. EyeMonitor         — eye height & width at a configurable BER target,
                          bathtub curve construction, eye opening ratio
  2. MuellerMullerTED   — timing error detector (baud-rate, Mueller-Müller
                          algorithm) for CDR phase error
  3. ErrorDetector      — combines both into a single control interface used
                          by AdaptiveEngine

Mueller-Müller timing error (symbol-rate CDR):
  e_MM[k] = y[k-1] * â[k] - y[k] * â[k-1]
  where y[k] = sampled voltage, â[k] = decided (sliced) symbol.
  Positive e_MM → phase too late; negative → phase too early.

Eye height = min vertical opening in an eye diagram across all UI phases.
Eye width  = fraction of UI over which eye height > threshold.

Reference:
  Mueller & Müller, "Timing Recovery in Digital Synchronous Data Receivers",
  IEEE Trans. Commun., 1976.
  Casas et al., "Eye Diagram Estimation", IEEE JSSC, 2016.

Usage:
    ed = ErrorDetector(n_levels=2, baud_rate=10e9)
    phase_err = ed.mm_phase_error(samples, decisions)
    eye_h, eye_w = ed.eye_opening(samples, decisions)
    report = ed.analyse(samples, decisions)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Sequence, Tuple
import numpy as np


class EyeMetrics(NamedTuple):
    height:       float   # V — vertical eye opening at centre phase
    width:        float   # UI — horizontal eye opening (fraction of 1 UI)
    opening_ratio: float  # dimensionless: eye_height / signal_amplitude
    phase_err:    float   # Mueller-Müller phase error estimate (normalised)
    ber_estimate: float   # rough Q-function BER estimate


# ── Mueller-Müller Timing Error Detector ────────────────────────────────────

class MuellerMullerTED:
    """
    Baud-rate timing error detector.

    Operates on sequences of (sample, decision) pairs already decimated to
    1 sample/symbol (no oversampling required).

    Parameters
    ----------
    accumulate : bool
        If True, running-average the raw error over multiple calls.
    gain : float
        Error detector gain scaling (normalises to [−1, +1]).
    """

    def __init__(self, accumulate: bool = True, gain: float = 1.0) -> None:
        self._accumulate = accumulate
        self._gain = gain
        self._prev_sample = 0.0
        self._prev_decision = 0.0
        self._error_accum = 0.0
        self._n_accum = 0

    def reset(self) -> None:
        self._prev_sample   = 0.0
        self._prev_decision = 0.0
        self._error_accum   = 0.0
        self._n_accum       = 0

    def update(
        self,
        samples: Sequence[float],
        decisions: Sequence[float],
    ) -> np.ndarray:
        """
        Compute per-symbol Mueller-Müller timing error.

        Parameters
        ----------
        samples   : float array — sampled analogue values (e.g. ±0.5 V)
        decisions : float array — slicer decisions (e.g. ±1 for NRZ)

        Returns
        -------
        np.ndarray
            Per-symbol timing error e_MM[k] for k = 1..N.
        """
        y = np.asarray(samples,   dtype=float)
        a = np.asarray(decisions, dtype=float)
        if len(y) != len(a):
            raise ValueError("samples and decisions must have equal length")

        errors = np.empty(len(y), dtype=float)
        yk_1 = self._prev_sample
        ak_1 = self._prev_decision

        for k in range(len(y)):
            # e_MM = y[k-1]*â[k] - y[k]*â[k-1]
            errors[k] = yk_1 * a[k] - y[k] * ak_1
            yk_1 = y[k]
            ak_1 = a[k]

        self._prev_sample   = yk_1
        self._prev_decision = ak_1

        errors *= self._gain
        if self._accumulate:
            self._error_accum += float(np.mean(errors))
            self._n_accum += 1
        return errors

    def average_error(self) -> float:
        if self._n_accum == 0:
            return 0.0
        return self._error_accum / self._n_accum

    def reset_accumulator(self) -> None:
        self._error_accum = 0.0
        self._n_accum = 0


# ── Eye Monitor ──────────────────────────────────────────────────────────────

class EyeMonitor:
    """
    Statistical eye monitor.

    Constructs a bathtub curve and estimates eye height/width from a
    1-sample/symbol sequence.  For a proper eye diagram, the caller should
    provide samples at multiple phase offsets; this class works with a single
    phase point and uses amplitude statistics.

    Parameters
    ----------
    n_levels : int
        2 for NRZ, 4 for PAM4.
    signal_amplitude : float
        Peak-to-peak signal amplitude in Volts (used for normalisation).
    """

    def __init__(self, n_levels: int = 2, signal_amplitude: float = 1.0) -> None:
        if n_levels not in (2, 4):
            raise ValueError("n_levels must be 2 (NRZ) or 4 (PAM4)")
        self._n_levels = n_levels
        self._amp = signal_amplitude

    def eye_height(
        self,
        samples: Sequence[float],
        decisions: Sequence[float],
    ) -> float:
        """
        Estimate vertical eye opening in Volts.

        Eye height ≈ mean(decided '1' samples) - mean(decided '0' samples)
        minus 3σ of the noise on each level.
        """
        y = np.asarray(samples,   dtype=float)
        a = np.asarray(decisions, dtype=float)
        levels = np.unique(a)

        if len(levels) < 2:
            return 0.0

        min_eye = float('inf')
        sorted_levels = np.sort(levels)

        for i in range(len(sorted_levels) - 1):
            lo_lev = sorted_levels[i]
            hi_lev = sorted_levels[i + 1]
            lo_samp = y[a == lo_lev]
            hi_samp = y[a == hi_lev]
            if len(lo_samp) < 3 or len(hi_samp) < 3:
                continue
            lo_top  = np.mean(lo_samp) + 3 * np.std(lo_samp)
            hi_bot  = np.mean(hi_samp) - 3 * np.std(hi_samp)
            opening = hi_bot - lo_top
            min_eye = min(min_eye, opening)

        return max(0.0, min_eye)

    def eye_width(
        self,
        samples_by_phase: Dict[float, Sequence[float]],
        decisions_by_phase: Dict[float, Sequence[float]],
        threshold_v: float = 0.0,
    ) -> float:
        """
        Estimate horizontal eye width in UI.

        Parameters
        ----------
        samples_by_phase   : dict mapping phase_offset (0..1 UI) → samples
        decisions_by_phase : dict mapping phase_offset → decisions
        threshold_v        : eye height threshold in Volts

        Returns
        -------
        float
            Eye width in UI (0–1).
        """
        open_phases = []
        for phase, samps in samples_by_phase.items():
            decs = decisions_by_phase[phase]
            h = self.eye_height(samps, decs)
            if h > threshold_v:
                open_phases.append(phase)

        if not open_phases:
            return 0.0
        phases = np.array(sorted(open_phases))
        # Measure largest contiguous open interval
        diffs = np.diff(phases)
        width = 0.0
        run = phases[1] - phases[0] if len(phases) > 1 else 0.0
        for i, d in enumerate(diffs):
            run += d
            width = max(width, run)
        return width

    def q_factor(
        self,
        samples: Sequence[float],
        decisions: Sequence[float],
    ) -> float:
        """
        Compute Q-factor = (μ_1 - μ_0) / (σ_0 + σ_1) for NRZ.
        Higher Q → lower BER.
        """
        y = np.asarray(samples,   dtype=float)
        a = np.asarray(decisions, dtype=float)
        hi = y[a > 0]
        lo = y[a < 0]
        if len(hi) < 2 or len(lo) < 2:
            return 0.0
        return (np.mean(hi) - np.mean(lo)) / (np.std(lo) + np.std(hi) + 1e-12)

    def ber_estimate(self, q: float) -> float:
        """Q-function BER estimate: BER ≈ 0.5 * erfc(Q / sqrt(2))."""
        from math import erfc, sqrt
        return 0.5 * erfc(q / sqrt(2))


# ── Combined ErrorDetector ────────────────────────────────────────────────────

class ErrorDetector:
    """
    Combined error detector for use by AdaptiveEngine.

    Outputs:
      - Mueller-Müller timing error (for CDR phase adjustment)
      - Eye metrics (for CTLE/VGA/DFE/FFE adaptation)

    Parameters
    ----------
    n_levels : int
        2 = NRZ, 4 = PAM4.
    signal_amplitude : float
        Full-swing peak-to-peak amplitude in Volts.
    baud_rate : float
        Symbol rate in Baud (used for informational output only).
    """

    def __init__(
        self,
        n_levels: int = 2,
        signal_amplitude: float = 1.0,
        baud_rate: float = 10e9,
    ) -> None:
        self._ted   = MuellerMullerTED(accumulate=True)
        self._eye   = EyeMonitor(n_levels=n_levels, signal_amplitude=signal_amplitude)
        self._baud  = baud_rate
        self._amp   = signal_amplitude

    def reset(self) -> None:
        self._ted.reset()

    def analyse(
        self,
        samples: Sequence[float],
        decisions: Sequence[float],
    ) -> EyeMetrics:
        """
        Full analysis pass: compute eye metrics + MM phase error.

        Parameters
        ----------
        samples   : analogue samples at the slicer output (1 sample/symbol)
        decisions : slicer decisions (±1 for NRZ, 0/1/2/3 for PAM4)

        Returns
        -------
        EyeMetrics
            Named tuple with height, width, opening_ratio, phase_err, ber_estimate.
        """
        mm_errors = self._ted.update(samples, decisions)
        phase_err = float(np.mean(mm_errors))

        eye_h = self._eye.eye_height(samples, decisions)
        eye_w = 0.5  # single-phase approximation; multi-phase caller can use eye_width()
        q     = self._eye.q_factor(samples, decisions)
        ber   = self._eye.ber_estimate(q)

        return EyeMetrics(
            height       = eye_h,
            width        = eye_w,
            opening_ratio= eye_h / (self._amp + 1e-12),
            phase_err    = phase_err,
            ber_estimate = ber,
        )

    def mm_phase_error(
        self,
        samples: Sequence[float],
        decisions: Sequence[float],
    ) -> float:
        """Return mean Mueller-Müller timing error for the current block."""
        errs = self._ted.update(samples, decisions)
        return float(np.mean(errs))

    def eye_opening(
        self,
        samples: Sequence[float],
        decisions: Sequence[float],
    ) -> Tuple[float, float]:
        """Return (eye_height_V, eye_opening_ratio)."""
        h = self._eye.eye_height(samples, decisions)
        return h, h / (self._amp + 1e-12)

    def __repr__(self) -> str:
        return f"ErrorDetector(baud={self._baud/1e9:.1f}Gbps)"
