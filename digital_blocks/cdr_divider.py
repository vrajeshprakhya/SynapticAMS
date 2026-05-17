"""
CDR Frequency Divider / Counter — Digital block in the Clock & Data Recovery loop

Divides the VCO output clock by a programmable ratio N (integer or fractional).
The divided clock feeds back to the Phase Detector to close the CDR loop.

Architecture options implemented:
  1. IntegerDivider  — toggles output every N/2 VCO cycles (÷N, duty-cycle aware)
  2. FractionalDivider — dual-modulus (÷N / ÷N+1) with Σ-Δ accumulator
                         for non-integer effective divide ratios

Context in SerDes CDR:
  VCO runs at data_rate × M (e.g. 10 GHz for 10 Gbps × 1).
  Typical CDR divide ratios: ÷4 (quarter-rate), ÷8, or ÷16 (for multi-phase CDR).
  The divider output feeds the Phase Detector at the baud rate.

Reference:
  Razavi, "Design of Analog CMOS ICs", 2001, Ch. 15 (PLL).
  Lee & Hajimiri, "Oscillator Phase Noise: A Tutorial", JSSC 2000.

Usage:
    div = IntegerDivider(n=4)
    for _ in range(32):
        out = div.step()           # step one VCO clock cycle

    fdiv = FractionalDivider(n_int=4, frac=0.5)
    for _ in range(64):
        out = fdiv.step()
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class IntegerDivider:
    """
    Synchronous integer frequency divider (÷N).

    The output toggles every N/2 input clock cycles (for even N, this gives
    50% duty cycle).  For odd N the output duty cycle is (N±1)/(2N).

    Parameters
    ----------
    n : int
        Divide ratio (≥ 2).
    """
    n: int = 4

    _count: int = field(default=0, init=False, repr=False)
    _out:   int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.n < 2:
            raise ValueError("Divide ratio must be >= 2")
        self._count = 0
        self._out = 0

    def step(self) -> int:
        """Advance one VCO clock edge. Returns current divider output (0 or 1)."""
        self._count += 1
        # Toggle at mid-period (rising edge) and at full-period (falling edge)
        # This produces a period of N input cycles (÷N frequency divider).
        half = (self.n + 1) // 2
        if self._count == half:
            self._out ^= 1
        if self._count >= self.n:
            self._count = 0
            self._out ^= 1
        return self._out

    def run(self, n_cycles: int) -> List[int]:
        """Run *n_cycles* VCO clock cycles and return the output waveform."""
        return [self.step() for _ in range(n_cycles)]

    def reset(self) -> None:
        self._count = 0
        self._out = 0

    @property
    def output(self) -> int:
        return self._out

    def effective_ratio(self) -> float:
        return float(self.n)


@dataclass
class FractionalDivider:
    """
    Fractional-N frequency divider using dual-modulus (÷N / ÷N+1) with
    first-order Σ-Δ accumulator.

    Effective divide ratio = n_int + frac  (e.g. n_int=4, frac=0.5 → ÷4.5)

    The Σ-Δ accumulator overflows whenever the fractional residue exceeds 1.0,
    at which point the modulus switches from N to N+1 for that cycle.
    This spreads the fractional cycle over time, achieving a precise average.

    Parameters
    ----------
    n_int : int
        Integer part of the divide ratio (≥ 2).
    frac : float
        Fractional part in [0.0, 1.0).
    """
    n_int: int   = 4
    frac:  float = 0.0

    _count:    int   = field(default=0,   init=False, repr=False)
    _out:      int   = field(default=0,   init=False, repr=False)
    _accum:    float = field(default=0.0, init=False, repr=False)
    _modulus:  int   = field(default=0,   init=False, repr=False)

    def __post_init__(self) -> None:
        if self.n_int < 2:
            raise ValueError("n_int must be >= 2")
        if not 0.0 <= self.frac < 1.0:
            raise ValueError("frac must be in [0.0, 1.0)")
        self._count   = 0
        self._out     = 0
        self._accum   = 0.0
        self._modulus = self.n_int

    def step(self) -> int:
        """Advance one VCO clock edge."""
        self._count += 1
        half = (self._modulus + 1) // 2
        if self._count == half:
            self._out ^= 1
        if self._count >= self._modulus:
            self._count = 0
            self._out  ^= 1
            # Σ-Δ accumulator: decide next modulus
            self._accum += self.frac
            if self._accum >= 1.0:
                self._accum  -= 1.0
                self._modulus = self.n_int + 1
            else:
                self._modulus = self.n_int
        return self._out

    def run(self, n_cycles: int) -> List[int]:
        return [self.step() for _ in range(n_cycles)]

    def reset(self) -> None:
        self._count   = 0
        self._out     = 0
        self._accum   = 0.0
        self._modulus = self.n_int

    @property
    def output(self) -> int:
        return self._out

    def effective_ratio(self) -> float:
        return self.n_int + self.frac

    def measured_ratio(self, n_vco_cycles: int = 10_000) -> float:
        """
        Empirically measure the effective divide ratio over *n_vco_cycles*.
        The divider is reset before measurement and the current position is
        restored afterwards.  Useful for validation.
        """
        saved_count  = self._count
        saved_out    = self._out
        saved_accum  = self._accum
        saved_modulus= self._modulus

        self.reset()
        transitions = 0
        prev = self._out
        for _ in range(n_vco_cycles):
            cur = self.step()
            if cur != prev:
                transitions += 1
            prev = cur

        # Restore state
        self._count   = saved_count
        self._out     = saved_out
        self._accum   = saved_accum
        self._modulus = saved_modulus

        # Each full cycle = 2 transitions
        full_cycles = transitions / 2.0
        return n_vco_cycles / full_cycles if full_cycles > 0 else float('inf')


class CDRDivider:
    """
    High-level CDR divider: wraps integer or fractional divider and adds
    a programmable reset / resync interface matching the Phase Detector input.

    Parameters
    ----------
    ratio : float
        Target divide ratio (e.g. 4, 4.5, 8.25).
    """

    def __init__(self, ratio: float = 4.0) -> None:
        n_int = int(ratio)
        frac  = ratio - n_int
        if abs(frac) < 1e-9:
            self._div: IntegerDivider | FractionalDivider = IntegerDivider(n=n_int)
        else:
            self._div = FractionalDivider(n_int=n_int, frac=round(frac, 12))
        self._ratio = ratio

    @property
    def ratio(self) -> float:
        return self._ratio

    def step(self) -> int:
        """Clock one VCO cycle. Returns the divided clock output."""
        return self._div.step()

    def run(self, n_cycles: int) -> List[int]:
        return self._div.run(n_cycles)

    def reset(self) -> None:
        self._div.reset()

    def set_ratio(self, ratio: float) -> None:
        """Change divide ratio at runtime (used by adaptive CDR)."""
        self.__init__(ratio)

    def effective_ratio(self) -> float:
        return self._div.effective_ratio()

    def __repr__(self) -> str:
        return f"CDRDivider(ratio={self._ratio})"
