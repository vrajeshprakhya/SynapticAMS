"""
TX Feed-Forward Equalizer (FFE) — Digital Pre-emphasis FIR Filter

Models the digital-domain TX equalizer that pre-distorts the data stream
to compensate for channel high-frequency loss.  The FIR filter output
drives the TX DAC (the next mixed-signal block in the chain).

Architecture:
  - 3 to 5 tap linear FIR with 1-UI tap spacing
  - Tap notation: c[-1] = precursor, c[0] = main cursor, c[1..] = postcursors
  - Constraint: sum(|c_i|) <= 1  (passive TX amplitude normalisation)
  - Output is a floating-point amplitude in [−1, +1] representing the
    analogue value sent to the TX DAC.

PCIe Gen3/4 Preset Coefficients (11 standard presets, IEEE 802.3 Annex 72A):
  Preset  c[-1]   c[0]   c[1]
  P0      0.000   1.000  0.000  (no EQ)
  P1      0.000   0.800 -0.200
  P2      0.000   0.667 -0.333
  P3      0.000   0.500 -0.500 (max de-emphasis)
  P4     -0.167   0.833  0.000 (pre-cursor only)
  P5     -0.167   0.667 -0.167
  P6     -0.250   0.750  0.000
  P7     -0.250   0.625 -0.125
  P8     -0.250   0.500 -0.250 (max 3-tap)
  P9     -0.125   0.625 -0.250
  P10    -0.083   0.667 -0.250

Reference: PCIe Base Spec 4.0, Table 4-29; IEEE 802.3-2018 Annex 72A

Usage:
    ffe = TxFFE(taps=[0.0, 1.0, 0.0])            # pass-through
    ffe = TxFFE.from_preset('P5')                 # PCIe Gen3 preset
    output = ffe.filter(symbols)                  # numpy array output
    ffe.set_taps([-0.1, 0.8, -0.1])               # runtime update
"""

from __future__ import annotations
from typing import List, Sequence, Union
import numpy as np


# PCIe Gen3/4 presets: [precursor c[-1], cursor c[0], postcursor c[1]]
PCIE_PRESETS: dict[str, List[float]] = {
    'P0':  [0.000,  1.000,  0.000],
    'P1':  [0.000,  0.800, -0.200],
    'P2':  [0.000,  0.667, -0.333],
    'P3':  [0.000,  0.500, -0.500],
    'P4':  [-0.167, 0.833,  0.000],
    'P5':  [-0.167, 0.667, -0.167],
    'P6':  [-0.250, 0.750,  0.000],
    'P7':  [-0.250, 0.625, -0.125],
    'P8':  [-0.250, 0.500, -0.250],
    'P9':  [-0.125, 0.625, -0.250],
    'P10': [-0.083, 0.667, -0.250],
}


class TxFFE:
    """
    TX feed-forward equalizer.

    Parameters
    ----------
    taps : list of float
        FIR tap coefficients. Index 0 = oldest sample (most precursor).
        For a 3-tap FFE: taps = [c_pre, c_cursor, c_post].
    normalize : bool
        If True, normalize taps so max output amplitude = 1.0.
        Default False — caller is responsible for constraint.
    """

    def __init__(
        self,
        taps: Sequence[float] | None = None,
        normalize: bool = False,
    ) -> None:
        if taps is None:
            taps = [0.0, 1.0, 0.0]
        self._taps = np.array(taps, dtype=float)
        self._normalize = normalize
        if normalize:
            self._taps = self._taps / np.sum(np.abs(self._taps))
        self._n_taps = len(self._taps)
        # History buffer: holds the last (n_taps-1) input samples
        self._history = np.zeros(self._n_taps - 1, dtype=float)

    # ── factory ─────────────────────────────────────────────────────────────

    @classmethod
    def from_preset(cls, preset: str, normalize: bool = False) -> "TxFFE":
        """Create a TxFFE from a named PCIe preset (P0–P10)."""
        if preset not in PCIE_PRESETS:
            raise ValueError(f"Unknown preset '{preset}'. Valid: {list(PCIE_PRESETS)}")
        return cls(taps=PCIE_PRESETS[preset], normalize=normalize)

    # ── API ──────────────────────────────────────────────────────────────────

    @property
    def taps(self) -> np.ndarray:
        return self._taps.copy()

    @property
    def n_taps(self) -> int:
        return self._n_taps

    def set_taps(self, taps: Sequence[float]) -> None:
        """Update tap coefficients at runtime (adaptive control interface)."""
        new = np.array(taps, dtype=float)
        if len(new) != self._n_taps:
            raise ValueError(
                f"Tap count mismatch: expected {self._n_taps}, got {len(new)}"
            )
        if self._normalize:
            new = new / np.sum(np.abs(new))
        self._taps = new

    def reset(self) -> None:
        """Clear internal history buffer (use at start of frame/packet)."""
        self._history[:] = 0.0

    def filter(self, symbols: Union[Sequence[float], np.ndarray]) -> np.ndarray:
        """
        Apply FIR pre-emphasis to a symbol stream.

        Parameters
        ----------
        symbols : array-like of float
            Input data symbols, typically ±1.0 for NRZ or PAM4 levels.

        Returns
        -------
        np.ndarray
            Equalized output stream (same length as input).  These values
            drive the TX DAC input in the next stage.
        """
        x = np.asarray(symbols, dtype=float)
        # Prepend history to handle edge effects
        x_padded = np.concatenate([self._history, x])
        # Convolve (full FIR)
        y = np.convolve(x_padded, self._taps, mode='full')
        # Use centered slice so output aligns with filter_stateless() (mode='same').
        # For n_taps taps: effective delay = (n_taps-1)//2, matching symmetric FIR group delay.
        half = (self._n_taps - 1) // 2
        start = self._n_taps - 1 + half
        out = y[start : start + len(x)]
        # Copy (not view) to avoid aliasing if caller holds a reference to symbols
        self._history = x[-(self._n_taps - 1):].copy()
        return out

    def filter_stateless(self, symbols: Union[Sequence[float], np.ndarray]) -> np.ndarray:
        """
        Same as filter() but does not update internal history.
        Useful for analysing a block in isolation.
        """
        x = np.asarray(symbols, dtype=float)
        return np.convolve(x, self._taps, mode='same')

    def frequency_response(self, n_fft: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute discrete-frequency response of the FIR filter.

        Returns
        -------
        (freqs, H_db)
            freqs  : normalised frequency axis [0, 0.5] (in units of f_baud)
            H_db   : magnitude response in dB
        """
        H = np.fft.rfft(self._taps, n=n_fft)
        freqs = np.fft.rfftfreq(n_fft)
        H_db  = 20 * np.log10(np.abs(H) + 1e-12)
        return freqs, H_db

    def group_delay(self, n_fft: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute group delay of the FIR filter (in samples).
        For a linear-phase FIR this is constant = (n_taps - 1) / 2.
        """
        import scipy.signal as sig  # optional dependency
        freqs, gd = sig.group_delay((self._taps, [1.0]), w=n_fft)
        return freqs / (2 * np.pi), gd  # normalise to [0, 0.5]

    def __repr__(self) -> str:
        tap_str = ", ".join(f"{t:+.4f}" for t in self._taps)
        return f"TxFFE(taps=[{tap_str}])"
