"""
8b/10b Line Decoder — inverse of encoder_8b10b.

Accepts 10-bit code words and returns:
  - decoded 8-bit data byte
  - is_k_char  : True if the received word is a K control character
  - code_err   : True if the 10-bit code is not a valid 8b/10b codeword
  - disp_err   : True if the received codeword has unexpected disparity
                 relative to the current running disparity state

Usage:
    dec = Decoder8b10b()
    byte, is_k, code_err, disp_err = dec.decode(0x17C)
    results = dec.decode_stream([0x17C, 0x264, ...])
"""

from __future__ import annotations
from typing import List, NamedTuple, Optional
from .encoder_8b10b import (
    _5B6B, _3B4B_DATA, _3B4B_DATA_ALT7, _5B6B_K, _3B4B_K,
    _ALT7_ROWS, _disparity, _rd_after,
)


class DecodeResult(NamedTuple):
    byte: int        # decoded data byte (0 if code_err)
    is_k: bool       # True for K (control) character
    code_err: bool   # True if 10-bit code is not a valid codeword
    disp_err: bool   # True if disparity violated running-disparity rule


# ── Build reverse lookup tables at import time ──────────────────────────────

def _build_reverse_tables():
    """
    Returns RD-aware decode dicts to avoid ambiguity between K and data chars
    that share the same 4-bit code words.

    Returns:
        decode6      : 6-bit code  → abcde (data)
        decode6_k    : 6-bit code  → x     (K chars, only K.28 unique codes)
        decode4_data_rdm : code4 → fgh when rd_after_6 == -1
        decode4_data_rdp : code4 → fgh when rd_after_6 == +1
        decode4_k_rdm    : code4 -> y  when rd_after_6 == -1
        decode4_k_rdp    : code4 -> y  when rd_after_6 == +1
        valid_k_pairs    : set of (code6, code4) that are valid K characters
    """
    decode6 = {}
    for abcde, (rdm, rdp) in enumerate(_5B6B):
        decode6[rdm] = abcde
        decode6[rdp] = abcde

    decode6_k = {}
    for x, (rdm, rdp) in _5B6B_K.items():
        decode6_k[rdm] = x
        decode6_k[rdp] = x

    # RD-aware 4-bit data decode (avoids K/data ambiguity)
    decode4_data_rdm = {}
    decode4_data_rdp = {}
    for fgh, (rdm, rdp) in enumerate(_3B4B_DATA):
        decode4_data_rdm[rdm] = fgh
        decode4_data_rdp[rdp] = fgh
    # Alt D.x.7
    decode4_data_rdm[_3B4B_DATA_ALT7[0]] = 7
    decode4_data_rdp[_3B4B_DATA_ALT7[1]] = 7

    decode4_k_rdm = {}
    decode4_k_rdp = {}
    for y, (rdm, rdp) in _3B4B_K.items():
        decode4_k_rdm[rdm] = y
        decode4_k_rdp[rdp] = y

    # Build the set of all valid K codeword pairs (code6, code4).
    # K.28.y: all y=0..7 are valid K characters.
    # K.23.7, K.27.7, K.29.7, K.30.7: only y=7 is valid K.
    valid_k_pairs: set[tuple[int, int]] = set()
    k28_rdm, k28_rdp = _5B6B_K[28]
    for y, (c4m, c4p) in _3B4B_K.items():
        for c6 in (k28_rdm, k28_rdp):
            valid_k_pairs.add((c6, c4m))
            valid_k_pairs.add((c6, c4p))
    # K.23/27/29/30 — only y=7 is a valid K character
    k7_rdm, k7_rdp = _3B4B_K[7]
    for kx in (23, 27, 29, 30):
        kx_rdm, kx_rdp = _5B6B_K[kx]
        for c6 in (kx_rdm, kx_rdp):
            valid_k_pairs.add((c6, k7_rdm))
            valid_k_pairs.add((c6, k7_rdp))

    return (decode6, decode6_k,
            decode4_data_rdm, decode4_data_rdp,
            decode4_k_rdm, decode4_k_rdp,
            valid_k_pairs)


(_DEC6, _DEC6_K,
 _DEC4_DATA_RDM, _DEC4_DATA_RDP,
 _DEC4_K_RDM, _DEC4_K_RDP,
 _VALID_K_PAIRS) = _build_reverse_tables()

# Valid 6-bit codes: union of all data and K 6-bit codes
_VALID6 = set(_DEC6.keys()) | set(_DEC6_K.keys())


class Decoder8b10b:
    """
    Stateful 8b/10b decoder with running-disparity tracking.

    Parameters
    ----------
    initial_rd : int
        Starting running disparity, -1 or +1. Must match the encoder.
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

    def decode(self, code: int) -> DecodeResult:
        """
        Decode a 10-bit code word.

        Parameters
        ----------
        code : int
            10-bit code word (bits 9..0 = abcdeifghj).

        Returns
        -------
        DecodeResult
            Named tuple (byte, is_k, code_err, disp_err).
        """
        if not 0 <= code <= 0x3FF:
            raise ValueError(f"code must be 0–1023, got {code}")

        code6 = (code >> 4) & 0x3F
        code4 = code & 0x0F

        # ── 6-bit block ──────────────────────────────────────────────────────
        if code6 not in _VALID6:
            self._update_rd(code6, 6)
            self._update_rd(code4, 4)
            return DecodeResult(0, False, True, False)

        d6 = _disparity(code6, 6)
        disp_err = False
        if d6 != 0:
            correct6 = (d6 > 0 and self._rd == -1) or (d6 < 0 and self._rd == 1)
            if not correct6:
                disp_err = True
        rd_after_6 = _rd_after(code6, 6, self._rd)

        # ── K-character detection using the precomputed valid-pair set ─────
        # (code6, code4) must be in the exact set of 12 valid K characters.
        # This avoids false K detection when K.23/27/29/30 share 5b6b with data.
        is_k = (code6, code4) in _VALID_K_PAIRS

        # ── 4-bit block disparity ─────────────────────────────────────────
        d4 = _disparity(code4, 4)
        if d4 != 0:
            correct4 = (d4 > 0 and rd_after_6 == -1) or (d4 < 0 and rd_after_6 == 1)
            if not correct4:
                disp_err = True
        self._rd = _rd_after(code4, 4, rd_after_6)

        # ── Decode abcde and fgh using RD-aware tables ────────────────────
        abcde = _DEC6_K.get(code6, _DEC6.get(code6, 0)) if is_k else _DEC6.get(code6, 0)

        if is_k:
            fgh = (_DEC4_K_RDM if rd_after_6 == -1 else _DEC4_K_RDP).get(code4, 0)
        else:
            fgh = (_DEC4_DATA_RDM if rd_after_6 == -1 else _DEC4_DATA_RDP).get(code4, 0)

        # Validate 4-bit code exists in the expected table
        lookup_set = (_DEC4_K_RDM if rd_after_6 == -1 else _DEC4_K_RDP) if is_k else \
                     (_DEC4_DATA_RDM if rd_after_6 == -1 else _DEC4_DATA_RDP)
        if code4 not in lookup_set:
            return DecodeResult(0, is_k, True, disp_err)

        byte = (fgh << 5) | abcde
        return DecodeResult(byte, is_k, False, disp_err)

    def decode_stream(self, codes: List[int]) -> List[DecodeResult]:
        return [self.decode(c) for c in codes]

    # ── internals ───────────────────────────────────────────────────────────

    def _update_rd(self, code: int, width: int) -> None:
        self._rd = _rd_after(code, width, self._rd)

    def __repr__(self) -> str:
        return f"Decoder8b10b(rd={self._rd:+d})"
