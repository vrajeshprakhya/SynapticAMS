"""
Adaptive Engine — LMS/Sign-LMS Equaliser Coefficient Adaptation

Implements the decision-directed LMS algorithm to continuously adapt the
tap coefficients of the RX equalizers (CTLE, VGA, DFE, TX-FFE) to minimise
the mean-squared error between the slicer output and the ideal decision.

Algorithm (standard LMS):
    ŷ[k]  = w^T x[k]             (equaliser output)
    e[k]  = d[k] - ŷ[k]         (error: decision - equalised sample)
    w[k+1]= w[k] + μ * e[k] * x[k]  (tap update)

Sign-LMS variant (hardware-friendly, only sign of e used):
    w[k+1]= w[k] + μ * sign(e[k]) * x[k]

Manages four sets of coefficients corresponding to the blocks they control:
  - FFE taps      → drives TxFFE.set_taps()
  - DFE taps      → drives DFE tap weight interface
  - CTLE control  → single scalar (boost dB) mapped to DAC code
  - VGA gain      → single scalar (linear gain) mapped to DAC code

Reference:
  Widrow & Hoff, "Adaptive Switching Circuits", WESCON, 1960.
  Haykin, "Adaptive Filter Theory", 4th ed., 2002, Ch. 9.
  Bazaragani & Johns, "MMSE Equaliser Design Optimisation for Wireline
    SerDes", ISSCC 2024.

Usage:
    engine = AdaptiveEngine(
        ffe_taps=3, dfe_taps=5,
        mu_ffe=0.005, mu_dfe=0.003,
        mu_ctle=0.01, mu_vga=0.01,
        sign_lms=True,
    )
    for symbols, decisions in symbol_stream:
        coeffs = engine.update(symbols, decisions)
        tx_ffe.set_taps(coeffs.ffe)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple
import numpy as np


@dataclass
class AdaptCoeffs:
    """Snapshot of all adapted coefficients after one update cycle."""
    ffe:   np.ndarray   # TX FFE taps (n_ffe,)
    dfe:   np.ndarray   # DFE feedback taps (n_dfe,)
    ctle:  float        # CTLE boost (dB, positive = boost high-freq)
    vga:   float        # VGA linear gain


class AdaptiveEngine:
    """
    Decision-directed LMS adaptive engine.

    Parameters
    ----------
    ffe_taps : int
        Number of TX FFE tap coefficients to adapt.
    dfe_taps : int
        Number of DFE feedback tap coefficients.
    mu_ffe : float
        LMS step size for TX FFE adaptation.
    mu_dfe : float
        LMS step size for DFE adaptation.
    mu_ctle : float
        Step size for CTLE control scalar.
    mu_vga : float
        Step size for VGA gain scalar.
    sign_lms : bool
        If True, use Sign-LMS (replaces e[k] with sign(e[k])).
        More hardware-friendly; slightly slower convergence.
    ffe_constraint : str
        'normalise' — keep |sum(ffe)| = 1 after each update.
        'clip'      — clip each tap to [−1, +1].
        None        — unconstrained.
    vga_range : tuple
        (min_gain, max_gain) for VGA clipping.
    ctle_range : tuple
        (min_boost_dB, max_boost_dB) for CTLE clipping.
    """

    def __init__(
        self,
        ffe_taps:       int   = 3,
        dfe_taps:       int   = 5,
        mu_ffe:         float = 0.005,
        mu_dfe:         float = 0.003,
        mu_ctle:        float = 0.01,
        mu_vga:         float = 0.005,
        sign_lms:       bool  = True,
        ffe_constraint: Optional[str] = 'normalise',
        vga_range:      Tuple[float, float] = (0.1, 4.0),
        ctle_range:     Tuple[float, float] = (0.0, 20.0),
    ) -> None:
        self._n_ffe    = ffe_taps
        self._n_dfe    = dfe_taps
        self._mu_ffe   = mu_ffe
        self._mu_dfe   = mu_dfe
        self._mu_ctle  = mu_ctle
        self._mu_vga   = mu_vga
        self._sign_lms = sign_lms
        self._ffe_constraint = ffe_constraint
        self._vga_range  = vga_range
        self._ctle_range = ctle_range

        # Initial coefficients: FFE = pass-through (main tap = 1), rest = 0
        self._w_ffe  = np.zeros(ffe_taps, dtype=float)
        if ffe_taps > 0:
            self._w_ffe[ffe_taps // 2] = 1.0  # centre tap = 1 (no pre-emphasis)

        self._w_dfe  = np.zeros(dfe_taps, dtype=float)
        self._ctle   = 0.0   # dB boost
        self._vga    = 1.0   # linear gain

        # DFE history buffer: last n_dfe decisions
        self._dfe_history = np.zeros(dfe_taps, dtype=float)

        # Convergence tracking
        self._mse_history: List[float] = []

    # ── public API ──────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all coefficients to initial state."""
        self.__init__(
            ffe_taps       = self._n_ffe,
            dfe_taps       = self._n_dfe,
            mu_ffe         = self._mu_ffe,
            mu_dfe         = self._mu_dfe,
            mu_ctle        = self._mu_ctle,
            mu_vga         = self._mu_vga,
            sign_lms       = self._sign_lms,
            ffe_constraint = self._ffe_constraint,
            vga_range      = self._vga_range,
            ctle_range     = self._ctle_range,
        )

    @property
    def coefficients(self) -> AdaptCoeffs:
        return AdaptCoeffs(
            ffe  = self._w_ffe.copy(),
            dfe  = self._w_dfe.copy(),
            ctle = self._ctle,
            vga  = self._vga,
        )

    @property
    def mse_history(self) -> List[float]:
        return self._mse_history.copy()

    def update(
        self,
        samples:   Sequence[float],
        decisions: Sequence[float],
    ) -> AdaptCoeffs:
        """
        Run one adaptation block.

        Parameters
        ----------
        samples   : received/equalised analogue samples (1 sample/symbol).
        decisions : slicer hard decisions (desired output).

        Returns
        -------
        AdaptCoeffs
            Updated coefficient snapshot after processing this block.
        """
        y = np.asarray(samples,   dtype=float)
        d = np.asarray(decisions, dtype=float)
        if len(y) != len(d):
            raise ValueError("samples and decisions must have equal length")

        mse_accum = 0.0
        n = len(y)

        for k in range(n):
            error = d[k] - y[k]
            mse_accum += error ** 2

            e_step = float(np.sign(error)) if self._sign_lms else float(error)

            # ── FFE adaptation ────────────────────────────────────────────
            if self._n_ffe > 0:
                # Proper LMS: Δw = μ·e·x where x is the centered input window
                half = self._n_ffe // 2
                x_vec = np.array([
                    y[k - half + j] if 0 <= k - half + j < n else 0.0
                    for j in range(self._n_ffe)
                ])
                self._w_ffe += self._mu_ffe * e_step * x_vec
                self._apply_ffe_constraint()

            # ── DFE adaptation (feedback ISI cancellation) ────────────────
            if self._n_dfe > 0:
                self._w_dfe += self._mu_dfe * e_step * self._dfe_history
                self._dfe_history = np.roll(self._dfe_history, 1)
                self._dfe_history[0] = d[k]

            # ── CTLE scalar adaptation ─────────────────────────────────────
            # Gradient estimate: if |error| is large → more boost needed
            ctle_grad = e_step * abs(y[k])
            self._ctle += self._mu_ctle * ctle_grad
            self._ctle  = float(np.clip(self._ctle, *self._ctle_range))

            # ── VGA gain adaptation ────────────────────────────────────────
            # Gradient estimate: error correlated with current sample magnitude
            vga_grad = e_step * y[k]
            self._vga += self._mu_vga * vga_grad
            self._vga  = float(np.clip(self._vga, *self._vga_range))

        self._mse_history.append(mse_accum / n)
        return self.coefficients

    def update_ffe_only(
        self,
        input_vectors: np.ndarray,
        errors: np.ndarray,
    ) -> np.ndarray:
        """
        Full vector LMS for TX FFE given pre-computed input matrix and errors.

        Parameters
        ----------
        input_vectors : (N, n_ffe) — sliding window of input samples
        errors        : (N,)       — per-symbol error signal

        Returns
        -------
        np.ndarray  Updated FFE taps.
        """
        if input_vectors.shape[1] != self._n_ffe:
            raise ValueError("input_vectors column count must equal n_ffe")
        for k in range(len(errors)):
            e = float(np.sign(errors[k])) if self._sign_lms else float(errors[k])
            self._w_ffe += self._mu_ffe * e * input_vectors[k]
        self._apply_ffe_constraint()
        return self._w_ffe.copy()

    # ── internals ───────────────────────────────────────────────────────────

    def _apply_ffe_constraint(self) -> None:
        if self._ffe_constraint == 'normalise':
            norm = np.sum(np.abs(self._w_ffe))
            if norm > 1e-9:
                self._w_ffe /= norm
        elif self._ffe_constraint == 'clip':
            self._w_ffe = np.clip(self._w_ffe, -1.0, 1.0)

    # ── convergence helpers ──────────────────────────────────────────────────

    def has_converged(self, window: int = 50, tol: float = 1e-4) -> bool:
        """
        Returns True if MSE variance over last *window* blocks is below *tol*.
        """
        if len(self._mse_history) < window:
            return False
        recent = self._mse_history[-window:]
        return float(np.var(recent)) < tol

    def __repr__(self) -> str:
        return (
            f"AdaptiveEngine(ffe_taps={self._n_ffe}, dfe_taps={self._n_dfe}, "
            f"sign_lms={self._sign_lms}, "
            f"mu_ffe={self._mu_ffe}, mu_dfe={self._mu_dfe})"
        )
