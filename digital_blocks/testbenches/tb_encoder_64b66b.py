"""
Testbench: 64b/66b Encoder / Decoder

Verifies:
  1. Encode→Decode round-trip for random 64-bit words
  2. Sync header is preserved correctly (01 for data, 10 for control)
  3. PRBS-58 self-synchronous scrambler descrambles without pre-shared seed
     (after an initial 58-bit warmup period)
  4. Invalid sync headers trigger sync_err
  5. All-same-bit inputs are scrambled (DC balance check)

Run:
    python -m digital_blocks.testbenches.tb_encoder_64b66b
    pytest digital_blocks/testbenches/tb_encoder_64b66b.py -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
import numpy as np
from digital_blocks.encoder_64b66b import Encoder64b66b, Decoder64b66b


class TestEncoder64b66b:

    def setup_method(self):
        self.enc = Encoder64b66b(seed=0)
        self.dec = Decoder64b66b(seed=0)

    def test_roundtrip_random_words(self):
        rng = np.random.default_rng(42)
        words = [int(x) for x in rng.integers(0, 2**63, size=200)]  # 63-bit safe
        blocks  = self.enc.encode_stream(words)
        results = self.dec.decode_stream(blocks)
        for i, (w, (d, ctrl, serr)) in enumerate(zip(words, results)):
            assert not serr,  f"sync_err at word {i}"
            assert not ctrl,  f"unexpected control flag at word {i}"
            assert d == w,    f"decode mismatch at word {i}: {w:#x} → {d:#x}"

    def test_sync_header_data(self):
        self.enc.reset()
        block = self.enc.encode(0xDEADBEEFCAFEBABE, is_control=False)
        header = (block >> 64) & 0x3
        assert header == 0b01, f"Data block header should be 01, got {header:02b}"

    def test_sync_header_control(self):
        self.enc.reset()
        block = self.enc.encode(0xDEADBEEFCAFEBABE, is_control=True)
        header = (block >> 64) & 0x3
        assert header == 0b10, f"Control block header should be 10, got {header:02b}"

    def test_invalid_header_triggers_sync_err(self):
        self.dec.reset()
        # Force invalid header 0b11
        bad_block = (0b11 << 64) | 0x0
        _, _, sync_err = self.dec.decode(bad_block)
        assert sync_err, "Header 0b11 should trigger sync_err"

    def test_dc_balance_scrambled(self):
        """All-ones input should be DC-balanced after scrambling."""
        self.enc.reset(seed=0)
        all_ones = (1 << 64) - 1
        ones_counts = []
        for _ in range(100):
            block = self.enc.encode(all_ones)
            payload = block & ((1 << 64) - 1)
            ones_counts.append(bin(payload).count('1'))
        avg_ones = np.mean(ones_counts)
        # Should be close to 32 ± 8 for uniform scrambling
        assert 20 < avg_ones < 44, f"Average 1s count {avg_ones:.1f} suggests poor DC balance"

    def test_roundtrip_all_zeros(self):
        self.enc.reset()
        self.dec.reset()
        block = self.enc.encode(0)
        data, ctrl, serr = self.dec.decode(block)
        assert not serr
        assert data == 0

    def test_roundtrip_all_ones(self):
        self.enc.reset()
        self.dec.reset()
        word = (1 << 64) - 1
        block = self.enc.encode(word)
        data, ctrl, serr = self.dec.decode(block)
        assert not serr
        assert data == word

    def test_self_sync_after_warmup(self):
        """
        With mismatched seed, descrambler should self-synchronise within 58 bits
        (i.e., within 1 block at 64 bits wide). Verify round-trip after 5 blocks.
        """
        enc = Encoder64b66b(seed=0)
        dec = Decoder64b66b(seed=0xDEAD)  # wrong seed
        rng = np.random.default_rng(7)
        words = [int(x) for x in rng.integers(0, 2**63, size=10)]
        blocks = [enc.encode(w) for w in words]
        # Feed all blocks to descrambler (warmup in first 1-2 blocks)
        results = [dec.decode(b) for b in blocks]
        # After block 1, should be synchronised
        for i in range(2, len(words)):
            d, _, serr = results[i]
            assert d == words[i], f"Self-sync failed at block {i}"


def _run_quick():
    enc = Encoder64b66b()
    dec = Decoder64b66b()
    print("64b/66b encode→decode round-trip (5 random words):")
    print(f"{'Word (hex)':>20}  {'Block[65:64]':>12}  {'Match':>5}")
    print("-" * 45)
    import random
    random.seed(123)
    for _ in range(5):
        w = random.randint(0, 2**64 - 1)
        enc.reset()
        dec.reset()
        block = enc.encode(w)
        d, ctrl, serr = dec.decode(block)
        match = "✓" if d == w and not serr else "✗"
        hdr = (block >> 64) & 0x3
        print(f"  0x{w:016X}  {'01' if hdr==1 else '10':>12}  {match:>5}")


if __name__ == '__main__':
    _run_quick()
    print("\nRunning pytest...")
    pytest.main([__file__, '-v'])
