"""
SerDes Digital Blocks — behavioral Python models for all blue (digital) blocks
in the SerDes architecture diagram.

Each module is self-contained and can be imported independently or simulated
via the testbenches in digital_blocks/testbenches/.

Blocks:
  encoder_8b10b  — IEEE 802.3 8b/10b line encoder with running disparity
  decoder_8b10b  — 8b/10b decoder with disparity/code error detection
  encoder_64b66b — 64b/66b encoder with PRBS-58 scrambler (10GbE/PCIe style)
  tx_ffe         — TX feed-forward equalizer (FIR pre-emphasis, 3–5 taps)
  cdr_divider    — Programmable integer/fractional frequency divider
  error_detector — Eye monitor + Mueller-Müller phase error detector
  adaptive_engine — LMS/Sign-LMS adaptive coefficient engine
"""

from .encoder_8b10b import Encoder8b10b
from .decoder_8b10b import Decoder8b10b
from .encoder_64b66b import Encoder64b66b, Decoder64b66b
from .tx_ffe import TxFFE
from .cdr_divider import CDRDivider
from .error_detector import ErrorDetector
from .adaptive_engine import AdaptiveEngine

__all__ = [
    "Encoder8b10b",
    "Decoder8b10b",
    "Encoder64b66b",
    "Decoder64b66b",
    "TxFFE",
    "CDRDivider",
    "ErrorDetector",
    "AdaptiveEngine",
]
