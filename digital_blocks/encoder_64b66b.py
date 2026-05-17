"""
64b/66b Line Encoder & Decoder — IEEE 802.3ae (10GbE) / PCIe Gen3+

Maps 64-bit payload → 66-bit block:
  Bits [65:64] = sync header (01 = data, 10 = control/ordered-set)
  Bits [63:0]  = scrambled payload (PRBS-58 self-synchronous scrambler)

Scrambler polynomial: G(x) = 1 + x^39 + x^58
The scrambler is self-synchronous: the descrambler uses the received
(possibly corrupted) bits as the shift-register input.

Overhead: 2/64 = 3.125% (vs. 8b/10b: 25%)

Reference: IEEE 802.3ae-2002, Clause 49 (64B/66B PCS)

Usage:
    enc = Encoder64b66b()
    block = enc.encode(data=0xDEADBEEFCAFEBABE, is_control=False)  # int 66 bits
    blocks = enc.encode_stream([0xAABB..., ...])

    dec = Decoder64b66b()
    data, is_control, sync_err = dec.decode(block)
"""

from __future__ import annotations
from typing import List, Tuple


# PRBS-58 polynomial taps (x^58 + x^39 + 1)
_PRBS58_LEN = 58
_PRBS58_TAP = 39  # second tap position (x^39)

_SYNC_DATA    = 0b01  # sync header for data blocks
_SYNC_CONTROL = 0b10  # sync header for control/ordered-set blocks


class _PRBS58:
    """
    Self-synchronous LFSR scrambler/descrambler.
    G(x) = 1 + x^39 + x^58.

    Self-synchronous means:
      - Encoder: scrambled_bit = data_bit XOR sr[57] XOR sr[38]
                 sr is shifted in with scrambled_bit (NOT data_bit)
      - Decoder: data_bit = scrambled_bit XOR sr[57] XOR sr[38]
                 sr is shifted in with scrambled_bit

    This ensures the descrambler locks without knowing the encoder state.
    """

    def __init__(self) -> None:
        self._sr = [0] * _PRBS58_LEN  # shift register, sr[0] = oldest

    def reset(self, seed: int = 0) -> None:
        bits = [(seed >> i) & 1 for i in range(_PRBS58_LEN)]
        self._sr = bits

    def _step(self, in_bit: int, fb_bit: int) -> int:
        """Compute output bit and shift register using fb_bit as new sr input."""
        out = in_bit ^ self._sr[_PRBS58_LEN - 1] ^ self._sr[_PRBS58_LEN - _PRBS58_TAP - 1]
        self._sr = [fb_bit] + self._sr[:-1]
        return out

    def scramble_bit(self, data_bit: int) -> int:
        """Scramble one bit (encoder mode: feed scrambled output into sr)."""
        s = data_bit ^ self._sr[_PRBS58_LEN - 1] ^ self._sr[_PRBS58_LEN - _PRBS58_TAP - 1]
        self._sr = [s] + self._sr[:-1]   # self-sync: sr fed with scrambled bit
        return s

    def descramble_bit(self, rx_bit: int) -> int:
        """Descramble one bit (decoder mode: feed received bit into sr)."""
        d = rx_bit ^ self._sr[_PRBS58_LEN - 1] ^ self._sr[_PRBS58_LEN - _PRBS58_TAP - 1]
        self._sr = [rx_bit] + self._sr[:-1]  # self-sync: sr fed with received bit
        return d

    def scramble_word(self, data: int, width: int = 64) -> int:
        """Scramble *width* bits of *data* (LSB first)."""
        result = 0
        for i in range(width):
            bit = (data >> i) & 1
            s = self.scramble_bit(bit)
            result |= (s << i)
        return result

    def descramble_word(self, data: int, width: int = 64) -> int:
        """Descramble *width* bits of *data* (LSB first)."""
        result = 0
        for i in range(width):
            bit = (data >> i) & 1
            d = self.descramble_bit(bit)
            result |= (d << i)
        return result


class Encoder64b66b:
    """
    64b/66b encoder with self-synchronous PRBS-58 scrambler.

    Produces 66-bit output words. Bit layout:
      bit65..bit64 = sync header
      bit63..bit0  = scrambled payload

    Parameters
    ----------
    seed : int
        Initial scrambler seed (0 is standard).
    """

    def __init__(self, seed: int = 0) -> None:
        self._scrambler = _PRBS58()
        self._scrambler.reset(seed)

    def reset(self, seed: int = 0) -> None:
        self._scrambler.reset(seed)

    def encode(self, data: int, is_control: bool = False) -> int:
        """
        Encode a 64-bit word into a 66-bit block.

        Parameters
        ----------
        data : int
            64-bit payload (0 to 2^64-1).
        is_control : bool
            True for ordered-set / control block (sync header = 10).

        Returns
        -------
        int
            66-bit block: bits [65:64] = sync header, bits [63:0] = scrambled.
        """
        if not 0 <= data < (1 << 64):
            raise ValueError("data must be a 64-bit unsigned integer")
        scrambled = self._scrambler.scramble_word(data, 64)
        header = _SYNC_CONTROL if is_control else _SYNC_DATA
        return (header << 64) | scrambled

    def encode_stream(self, words: List[int], control_flags: List[bool] | None = None) -> List[int]:
        """Encode a list of 64-bit words to 66-bit blocks."""
        if control_flags is None:
            control_flags = [False] * len(words)
        return [self.encode(w, f) for w, f in zip(words, control_flags)]

    def __repr__(self) -> str:
        return "Encoder64b66b()"


class Decoder64b66b:
    """
    64b/66b decoder with self-synchronous PRBS-58 descrambler.

    Parameters
    ----------
    seed : int
        Initial descrambler seed — irrelevant in self-synchronous mode
        after an initial lock period of 58 bits.
    """

    def __init__(self, seed: int = 0) -> None:
        self._descrambler = _PRBS58()
        self._descrambler.reset(seed)

    def reset(self, seed: int = 0) -> None:
        self._descrambler.reset(seed)

    def decode(self, block: int) -> Tuple[int, bool, bool]:
        """
        Decode a 66-bit block.

        Returns
        -------
        (data, is_control, sync_err)
            data       : 64-bit descrambled payload
            is_control : True for control block
            sync_err   : True if sync header is neither 01 nor 10
        """
        if not 0 <= block < (1 << 66):
            raise ValueError("block must be a 66-bit integer")
        header   = (block >> 64) & 0x3
        payload  = block & ((1 << 64) - 1)
        sync_err = header not in (_SYNC_DATA, _SYNC_CONTROL)
        is_ctrl  = (header == _SYNC_CONTROL)
        data     = self._descrambler.descramble_word(payload, 64)
        return data, is_ctrl, sync_err

    def decode_stream(self, blocks: List[int]) -> List[Tuple[int, bool, bool]]:
        return [self.decode(b) for b in blocks]

    def __repr__(self) -> str:
        return "Decoder64b66b()"
