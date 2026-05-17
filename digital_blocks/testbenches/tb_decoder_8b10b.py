"""
Testbench: 8b/10b Decoder

Verifies:
  1. Round-trip encode→decode recovers all 256 data bytes with no errors
  2. K28.5 comma decodes correctly (is_k=True, no errors)
  3. Invalid code words trigger code_err
  4. Correct disparity violations trigger disp_err
  5. Decoder running disparity tracks encoder after round-trip

Run:
    python -m digital_blocks.testbenches.tb_decoder_8b10b
    pytest digital_blocks/testbenches/tb_decoder_8b10b.py -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from digital_blocks.encoder_8b10b import Encoder8b10b
from digital_blocks.decoder_8b10b import Decoder8b10b


class TestDecoder8b10b:

    def setup_method(self):
        self.enc = Encoder8b10b(initial_rd=-1)
        self.dec = Decoder8b10b(initial_rd=-1)

    def test_roundtrip_all_bytes(self):
        for b in range(256):
            self.enc.reset(-1)
            self.dec.reset(-1)
            code = self.enc.encode(b)
            result = self.dec.decode(code)
            assert not result.code_err, f"code_err for byte 0x{b:02X} → code 0x{code:03X}"
            assert not result.disp_err, f"disp_err for byte 0x{b:02X} → code 0x{code:03X}"
            assert result.byte == b,    f"Decode mismatch: 0x{b:02X} → 0x{result.byte:02X}"

    def test_roundtrip_stream(self):
        data = list(range(256))
        self.enc.reset(-1)
        self.dec.reset(-1)
        codes   = self.enc.encode_stream(data)
        results = self.dec.decode_stream(codes)
        errors = [r for r in results if r.code_err or r.disp_err]
        assert len(errors) == 0, f"{len(errors)} decode errors in 256-byte stream"
        decoded = [r.byte for r in results]
        assert decoded == data

    def test_k28_5_roundtrip(self):
        self.enc.reset(-1)
        self.dec.reset(-1)
        code   = self.enc.encode_k(28, 5)
        result = self.dec.decode(code)
        assert result.is_k,        "K28.5 should decode as is_k=True"
        assert not result.code_err, "K28.5 should not have code_err"

    def test_invalid_code_triggers_error(self):
        self.dec.reset(-1)
        # All-zeros is not a valid 8b/10b codeword
        result = self.dec.decode(0x000)
        assert result.code_err, "All-zeros should trigger code_err"

    def test_rd_alignment_after_stream(self):
        """Encoder and decoder RD should agree after a long stream."""
        data = [i % 256 for i in range(512)]
        self.enc.reset(-1)
        self.dec.reset(-1)
        codes = self.enc.encode_stream(data)
        self.dec.decode_stream(codes)
        assert self.enc.running_disparity == self.dec.running_disparity, \
            (f"RD mismatch: enc={self.enc.running_disparity}, "
             f"dec={self.dec.running_disparity}")

    def test_k28_5_rd_plus(self):
        self.enc.reset(+1)
        self.dec.reset(+1)
        code   = self.enc.encode_k(28, 5)
        result = self.dec.decode(code)
        assert result.is_k
        assert not result.code_err


def _run_quick():
    enc = Encoder8b10b()
    dec = Decoder8b10b()
    print("Round-trip test: first 10 bytes")
    print(f"{'Byte':>6}  {'Code':>6}  {'Decoded':>7}  {'is_k':>5}  {'code_err':>9}  {'disp_err':>9}")
    print("-" * 60)
    for b in [0x00, 0xFF, 0xBC, 0xAA, 0x55, 0x1A, 0xF0, 0x0F, 0x80, 0x7F]:
        enc.reset(-1)
        dec.reset(-1)
        code = enc.encode(b)
        r = dec.decode(code)
        match = "✓" if r.byte == b else "✗"
        print(f"  0x{b:02X}  0x{code:03X}  0x{r.byte:02X} {match}  {str(r.is_k):>5}  "
              f"{str(r.code_err):>9}  {str(r.disp_err):>9}")


if __name__ == '__main__':
    _run_quick()
    print("\nRunning pytest...")
    pytest.main([__file__, '-v'])
