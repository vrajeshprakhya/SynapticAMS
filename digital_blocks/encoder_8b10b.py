"""
8b/10b Line Encoder — IEEE 802.3 / IBM Widmer-Franaszek (1983)

Maps each 8-bit input byte to a 10-bit line code with DC balance.
Maintains a Running Disparity (RD) state (±1) across the byte stream.

Output bit ordering: abcdeifghj (LSB first) — same as TX wire order
for standard Gigabit/Fibre Channel / USB3 SerDes.

Usage:
    enc = Encoder8b10b()
    code = enc.encode(0xBC)          # returns int (10-bit)
    codes = enc.encode_stream([0xBC, 0x00, 0xFF])
    is_special, code = enc.encode_k(28, 5)   # K28.5 comma character
"""

from __future__ import annotations
from typing import List, Tuple, Optional


# ── 5B/6B lookup: (rd_minus_code, rd_plus_code) for abcde = 0..31 ──────────
# Bit order: bit5 = 'a', bit0 = 'i'  (transmitted a first)
# Source: IBM Widmer-Franaszek 1983, Table 1; cross-checked against IEEE 802.3
_5B6B: List[Tuple[int, int]] = [
    (0b100111, 0b011000),  # D.00  disparity +2 / -2
    (0b011101, 0b100010),  # D.01
    (0b101101, 0b010010),  # D.02
    (0b110001, 0b110001),  # D.03  disparity 0 (neutral)
    (0b110101, 0b001010),  # D.04
    (0b101001, 0b101001),  # D.05  neutral
    (0b011001, 0b011001),  # D.06  neutral
    (0b111000, 0b000111),  # D.07
    (0b111001, 0b000110),  # D.08
    (0b100101, 0b100101),  # D.09  neutral
    (0b010101, 0b010101),  # D.10  neutral
    (0b110100, 0b110100),  # D.11  neutral
    (0b001101, 0b001101),  # D.12  neutral
    (0b101100, 0b101100),  # D.13  neutral
    (0b011100, 0b011100),  # D.14  neutral
    (0b010111, 0b101000),  # D.15
    (0b011011, 0b100100),  # D.16
    (0b100011, 0b100011),  # D.17  neutral
    (0b010011, 0b010011),  # D.18  neutral
    (0b110010, 0b110010),  # D.19  neutral
    (0b001011, 0b001011),  # D.20  neutral
    (0b101010, 0b101010),  # D.21  neutral
    (0b011010, 0b011010),  # D.22  neutral
    (0b111010, 0b000101),  # D.23
    (0b110011, 0b001100),  # D.24
    (0b100110, 0b100110),  # D.25  neutral
    (0b010110, 0b010110),  # D.26  neutral
    (0b110110, 0b001001),  # D.27
    (0b001110, 0b001110),  # D.28  neutral
    (0b101110, 0b010001),  # D.29
    (0b011110, 0b100001),  # D.30
    (0b101011, 0b010100),  # D.31
]

# ── 3B/4B lookup for data characters: (rd_minus, rd_plus) for fgh = 0..7 ───
# Bit order: bit3 = 'f', bit0 = 'j'
_3B4B_DATA: List[Tuple[int, int]] = [
    (0b1011, 0b0100),  # D.x.0
    (0b1001, 0b1001),  # D.x.1  neutral  (alt 0110 in some sequences)
    (0b0101, 0b0101),  # D.x.2  neutral  (alt 1010)
    (0b1100, 0b0011),  # D.x.3
    (0b1101, 0b0010),  # D.x.4
    (0b1010, 0b1010),  # D.x.5  neutral
    (0b0110, 0b0110),  # D.x.6  neutral
    (0b1110, 0b0001),  # D.x.7  (alt 0111 for D.17/18/20.7)
]

# Alternate 3B/4B for D.x.7 — used for D.17.7, D.18.7, D.20.7 to avoid
# merging with K28.7.  Selected when preceding 6-bit block has RD+ code
# (i.e., after encoding the 5b6b block the new RD would be +1).
_3B4B_DATA_ALT7: Tuple[int, int] = (0b0111, 0b1000)

# ── 5B/6B for K characters (special control codes) ──────────────────────────
_5B6B_K: dict[int, Tuple[int, int]] = {
    28: (0b001111, 0b110000),  # K.28.x — the comma anchor
    23: (0b111010, 0b000101),  # same as D.23 by coincidence
    27: (0b110110, 0b001001),
    29: (0b101110, 0b010001),
    30: (0b011110, 0b100001),
}

# ── 3B/4B for K characters ───────────────────────────────────────────────────
_3B4B_K: dict[int, Tuple[int, int]] = {
    0: (0b1011, 0b0100),
    1: (0b0110, 0b1001),  # K.x.1 — inverted vs data
    2: (0b1010, 0b0101),  # K.x.2 — inverted vs data
    3: (0b1100, 0b0011),
    4: (0b0100, 0b1011),  # K.x.4 — inverted vs data
    5: (0b0101, 0b1010),  # K.x.5
    6: (0b1001, 0b0110),  # K.x.6
    7: (0b0111, 0b1000),  # K.x.7
}

# Set of (abcde, fgh) pairs that use the alternate 3b4b for y=7
_ALT7_ROWS = {17, 18, 20}


def _disparity(code: int, width: int) -> int:
    """Return disparity (+2, 0, or -2) of a code word."""
    ones = bin(code).count('1')
    return ones * 2 - width


def _rd_after(code: int, width: int, current_rd: int) -> int:
    """Compute new running disparity after transmitting *code*."""
    d = _disparity(code, width)
    if d == 0:
        return current_rd
    return 1 if d > 0 else -1


class Encoder8b10b:
    """
    Stateful 8b/10b encoder. Maintains running disparity across calls.

    Parameters
    ----------
    initial_rd : int
        Starting running disparity, either -1 or +1. Defaults to -1
        per IEEE 802.3 convention.
    """

    def __init__(self, initial_rd: int = -1) -> None:
        if initial_rd not in (-1, 1):
            raise ValueError("initial_rd must be -1 or +1")
        self._rd = initial_rd

    # ── public API ──────────────────────────────────────────────────────────

    @property
    def running_disparity(self) -> int:
        return self._rd

    def reset(self, rd: int = -1) -> None:
        self._rd = rd

    def encode(self, byte: int) -> int:
        """
        Encode one data byte (0–255) to a 10-bit code word.
        Updates running disparity.

        Returns
        -------
        int
            10-bit code, bit9 = 'a' (first transmitted), bit0 = 'j'.
        """
        if not 0 <= byte <= 255:
            raise ValueError(f"byte must be 0–255, got {byte}")
        abcde = byte & 0x1F         # lower 5 bits
        fgh   = (byte >> 5) & 0x07  # upper 3 bits
        return self._encode_data(abcde, fgh)

    def encode_k(self, x: int, y: int) -> int:
        """
        Encode a K (control) character K.x.y.
        Standard K characters: K28.0–K28.7, K23.7, K27.7, K29.7, K30.7.

        Returns
        -------
        int
            10-bit code word.

        Raises
        ------
        ValueError
            If the requested K.x.y is not a valid special character.
        """
        if x not in _5B6B_K:
            raise ValueError(f"K.{x}.{y} — unsupported K-code x={x}")
        if y not in _3B4B_K:
            raise ValueError(f"K.{x}.{y} — unsupported K-code y={y}")
        return self._encode_raw(_5B6B_K[x], _3B4B_K[y])

    def encode_stream(self, data: List[int], k_flags: Optional[List[bool]] = None) -> List[int]:
        """
        Encode a list of bytes. Optionally mark some as K characters
        via *k_flags* (same length as *data*).

        For K characters the byte value is interpreted as (x << 3 | y).
        """
        if k_flags is None:
            k_flags = [False] * len(data)
        if len(data) != len(k_flags):
            raise ValueError("data and k_flags must have equal length")
        result = []
        for byte, is_k in zip(data, k_flags):
            if is_k:
                x = (byte >> 3) & 0x1F
                y = byte & 0x07
                result.append(self.encode_k(x, y))
            else:
                result.append(self.encode(byte))
        return result

    # ── internals ───────────────────────────────────────────────────────────

    def _encode_data(self, abcde: int, fgh: int) -> int:
        rd_minus_6, rd_plus_6 = _5B6B[abcde]
        code6 = rd_minus_6 if self._rd == -1 else rd_plus_6
        rd_after_6 = _rd_after(code6, 6, self._rd)

        # Choose 3b4b table (handle D.x.7 alternate for abcde ∈ {17,18,20})
        if fgh == 7 and abcde in _ALT7_ROWS:
            rd_minus_4, rd_plus_4 = _3B4B_DATA_ALT7
        else:
            rd_minus_4, rd_plus_4 = _3B4B_DATA[fgh]

        code4 = rd_minus_4 if rd_after_6 == -1 else rd_plus_4
        self._rd = _rd_after(code4, 4, rd_after_6)

        # Pack: code6 carries bits abcdei (6 bits MSB), code4 carries fghj (4 bits LSB)
        return (code6 << 4) | code4

    def _encode_raw(
        self,
        table6: Tuple[int, int],
        table4: Tuple[int, int],
    ) -> int:
        rd_minus_6, rd_plus_6 = table6
        code6 = rd_minus_6 if self._rd == -1 else rd_plus_6
        rd_after_6 = _rd_after(code6, 6, self._rd)

        rd_minus_4, rd_plus_4 = table4
        code4 = rd_minus_4 if rd_after_6 == -1 else rd_plus_4
        self._rd = _rd_after(code4, 4, rd_after_6)

        return (code6 << 4) | code4

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def code_to_bits(code: int, width: int = 10) -> str:
        """Return bit string MSB-first."""
        return format(code, f'0{width}b')

    def __repr__(self) -> str:
        return f"Encoder8b10b(rd={self._rd:+d})"
