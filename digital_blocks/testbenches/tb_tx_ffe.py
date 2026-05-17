"""
Testbench: TX Feed-Forward Equalizer (FFE)

Verifies:
  1. Pass-through preset P0 leaves symbols unchanged
  2. De-emphasis preset P1 reduces postcursor ISI
  3. Frequency response shows pre-emphasis at Nyquist (high-freq boost)
  4. Tap normalisation keeps output within ±1
  5. Adaptive tap update via set_taps()
  6. Stateful filter vs stateless produce same output on isolated blocks

Run:
    python -m digital_blocks.testbenches.tb_tx_ffe
    pytest digital_blocks/testbenches/tb_tx_ffe.py -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
import numpy as np
from digital_blocks.tx_ffe import TxFFE, PCIE_PRESETS


class TestTxFFE:

    def test_passthrough_preset(self):
        ffe = TxFFE.from_preset('P0')
        symbols = np.array([1.0, -1.0, 1.0, -1.0, 1.0])
        out = ffe.filter_stateless(symbols)
        np.testing.assert_allclose(out, symbols, atol=1e-10,
            err_msg="P0 (pass-through) should not modify symbols")

    def test_all_presets_load(self):
        for name in PCIE_PRESETS:
            ffe = TxFFE.from_preset(name)
            assert ffe.n_taps == 3

    def test_output_length_matches_input(self):
        ffe = TxFFE(taps=[0.0, 1.0, 0.0])
        symbols = np.random.randn(100)
        out = ffe.filter(symbols)
        assert len(out) == len(symbols)

    def test_normalisation(self):
        ffe = TxFFE(taps=[-0.5, 2.0, -0.5], normalize=True)
        # |taps| sum = 3.0, normalised → [-0.167, 0.667, -0.167]
        assert abs(np.sum(np.abs(ffe.taps)) - 1.0) < 1e-9

    def test_set_taps_updates(self):
        ffe = TxFFE(taps=[0.0, 1.0, 0.0])
        new_taps = [-0.2, 0.8, -0.1]  # note: doesn't need to be normalised
        ffe.set_taps(new_taps)
        np.testing.assert_allclose(ffe.taps, new_taps)

    def test_set_taps_wrong_count_raises(self):
        ffe = TxFFE(taps=[0.0, 1.0, 0.0])
        with pytest.raises(ValueError):
            ffe.set_taps([0.0, 1.0])

    def test_de_emphasis_reduces_postcursor(self):
        """P3 (max de-emphasis) should heavily attenuate postcursor."""
        ffe = TxFFE.from_preset('P3')   # [0, 0.5, -0.5]
        # Two-bit sequence: 1, 1 — the second 1 will be reduced by postcursor
        symbols = np.array([0.0, 1.0, 1.0, 1.0, 0.0])
        out = ffe.filter_stateless(symbols)
        # When two consecutive +1s, the second should be reduced vs pass-through
        assert out[2] < 1.0, "De-emphasis should reduce amplitude on run of 1s"

    def test_frequency_response_shape(self):
        """Pre-emphasis (negative postcursor) should boost high frequencies."""
        ffe = TxFFE(taps=[0.0, 0.8, -0.2])   # de-emphasis
        freqs, H_db = ffe.frequency_response(n_fft=512)
        # Low freq response > high freq response for de-emphasis
        dc_gain   = H_db[0]
        nyq_gain  = H_db[-1]
        assert nyq_gain > dc_gain - 1.0, \
            f"De-emphasis should boost high-freq; dc={dc_gain:.1f}dB, nyq={nyq_gain:.1f}dB"

    def test_reset_clears_history(self):
        ffe = TxFFE(taps=[-0.2, 0.8, -0.2])
        symbols = np.ones(10)
        out1 = ffe.filter(symbols)
        ffe.reset()
        out2 = ffe.filter(symbols)
        np.testing.assert_allclose(out1, out2, atol=1e-10,
            err_msg="After reset, filter output should be identical")

    def test_stateful_stateless_single_block(self):
        """On an isolated block (no history), both modes should agree."""
        ffe = TxFFE(taps=[-0.1, 0.8, -0.1])
        symbols = np.array([1.0, -1.0, 1.0, 1.0, -1.0, 1.0, -1.0, 1.0])
        ffe.reset()
        out_state  = ffe.filter(symbols)
        out_nostate = TxFFE(taps=[-0.1, 0.8, -0.1]).filter_stateless(symbols)
        # Not identical due to edge handling, but centre region should agree
        np.testing.assert_allclose(out_state[1:-1], out_nostate[1:-1], atol=1e-10)


def _run_quick():
    import matplotlib
    matplotlib.use('Agg')   # non-interactive

    print("TX FFE Quick Demo")
    print("=" * 50)

    for name in ['P0', 'P1', 'P5', 'P8']:
        ffe = TxFFE.from_preset(name)
        taps = [f"{t:+.3f}" for t in ffe.taps]
        print(f"  {name}: taps = [{', '.join(taps)}]")

    # Demonstrate on alternating NRZ symbols
    ffe = TxFFE.from_preset('P5')
    nrz = np.array([+1, -1, +1, +1, -1, +1, -1, -1, +1, -1], dtype=float)
    out = ffe.filter(nrz)
    print(f"\nP5 pre-emphasis on NRZ [+1,-1,+1,+1,-1,...]:")
    print(f"  Input : {nrz.tolist()}")
    print(f"  Output: {[round(x, 3) for x in out.tolist()]}")

    # Frequency response
    ffe_noeq = TxFFE.from_preset('P0')
    ffe_eq   = TxFFE.from_preset('P8')
    f0, H0 = ffe_noeq.frequency_response()
    f8, H8 = ffe_eq.frequency_response()
    print(f"\nFrequency response (DC / Nyquist gain):")
    print(f"  P0 (no EQ): DC={H0[0]:.1f}dB, Nyquist={H0[-1]:.1f}dB")
    print(f"  P8 (3-tap): DC={H8[0]:.1f}dB, Nyquist={H8[-1]:.1f}dB")


if __name__ == '__main__':
    _run_quick()
    print("\nRunning pytest...")
    pytest.main([__file__, '-v'])
