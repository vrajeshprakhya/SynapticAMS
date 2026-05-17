"""
Testbench: CDR Frequency Divider / Counter

Verifies:
  1. Integer divider produces correct divide ratio (measured from transitions)
  2. Fractional divider achieves correct effective ratio over long run
  3. CDRDivider wrapper selects integer vs fractional correctly
  4. Reset restores initial state
  5. Ratio change via set_ratio() takes effect immediately

Run:
    python -m digital_blocks.testbenches.tb_cdr_divider
    pytest digital_blocks/testbenches/tb_cdr_divider.py -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
import numpy as np
from digital_blocks.cdr_divider import IntegerDivider, FractionalDivider, CDRDivider


def _measure_ratio(waveform):
    """Count transitions and derive divide ratio from waveform."""
    transitions = sum(1 for i in range(1, len(waveform)) if waveform[i] != waveform[i-1])
    if transitions < 2:
        return float('inf')
    return len(waveform) / (transitions / 2.0)


class TestIntegerDivider:

    def test_divide_by_2(self):
        div = IntegerDivider(n=2)
        wave = div.run(1000)
        ratio = _measure_ratio(wave)
        assert abs(ratio - 2.0) < 0.1, f"÷2 measured ratio {ratio:.3f}"

    def test_divide_by_4(self):
        div = IntegerDivider(n=4)
        wave = div.run(10000)
        ratio = _measure_ratio(wave)
        assert abs(ratio - 4.0) < 0.1, f"÷4 measured ratio {ratio:.3f}"

    def test_divide_by_8(self):
        div = IntegerDivider(n=8)
        wave = div.run(10000)
        ratio = _measure_ratio(wave)
        assert abs(ratio - 8.0) < 0.1, f"÷8 measured ratio {ratio:.3f}"

    def test_divide_by_16(self):
        div = IntegerDivider(n=16)
        wave = div.run(10000)
        ratio = _measure_ratio(wave)
        assert abs(ratio - 16.0) < 0.2, f"÷16 measured ratio {ratio:.3f}"

    def test_reset_restores_state(self):
        div = IntegerDivider(n=4)
        div.run(7)       # mid-cycle
        div.reset()
        wave1 = div.run(100)
        div.reset()
        wave2 = div.run(100)
        assert wave1 == wave2, "Reset should produce identical output"

    def test_invalid_n_raises(self):
        with pytest.raises(ValueError):
            IntegerDivider(n=1)

    def test_effective_ratio(self):
        div = IntegerDivider(n=5)
        assert div.effective_ratio() == 5.0


class TestFractionalDivider:

    def test_divide_by_4_5(self):
        div = FractionalDivider(n_int=4, frac=0.5)
        ratio = div.measured_ratio(n_vco_cycles=100_000)
        assert abs(ratio - 4.5) < 0.05, f"÷4.5 measured ratio {ratio:.4f}"

    def test_divide_by_4_25(self):
        div = FractionalDivider(n_int=4, frac=0.25)
        ratio = div.measured_ratio(n_vco_cycles=100_000)
        assert abs(ratio - 4.25) < 0.05, f"÷4.25 measured ratio {ratio:.4f}"

    def test_divide_by_8_333(self):
        div = FractionalDivider(n_int=8, frac=1/3)
        ratio = div.measured_ratio(n_vco_cycles=300_000)
        assert abs(ratio - 8.333) < 0.05, f"÷8.333 measured ratio {ratio:.4f}"

    def test_integer_frac_zero_is_pure_integer(self):
        div = FractionalDivider(n_int=4, frac=0.0)
        wave = div.run(10000)
        ratio = _measure_ratio(wave)
        assert abs(ratio - 4.0) < 0.1

    def test_reset(self):
        div = FractionalDivider(n_int=4, frac=0.5)
        div.run(19)
        div.reset()
        wave1 = div.run(100)
        div.reset()
        wave2 = div.run(100)
        assert wave1 == wave2

    def test_invalid_frac_raises(self):
        with pytest.raises(ValueError):
            FractionalDivider(n_int=4, frac=1.0)
        with pytest.raises(ValueError):
            FractionalDivider(n_int=4, frac=-0.1)


class TestCDRDivider:

    def test_integer_ratio_selects_integer_divider(self):
        div = CDRDivider(ratio=4.0)
        assert isinstance(div._div, IntegerDivider)

    def test_fractional_ratio_selects_fractional_divider(self):
        div = CDRDivider(ratio=4.5)
        assert isinstance(div._div, FractionalDivider)

    def test_ratio_4(self):
        div = CDRDivider(ratio=4)
        wave = div.run(10000)
        ratio = _measure_ratio(wave)
        assert abs(ratio - 4.0) < 0.1

    def test_ratio_4_5(self):
        div = CDRDivider(ratio=4.5)
        wave = div.run(100_000)
        ratio = _measure_ratio(wave)
        assert abs(ratio - 4.5) < 0.1

    def test_set_ratio_changes_behaviour(self):
        div = CDRDivider(ratio=4.0)
        div.reset()
        wave4 = div.run(10000)
        r4 = _measure_ratio(wave4)
        div.set_ratio(8.0)
        div.reset()
        wave8 = div.run(10000)
        r8 = _measure_ratio(wave8)
        assert abs(r4 - 4.0) < 0.2
        assert abs(r8 - 8.0) < 0.2


def _run_quick():
    print("CDR Divider Quick Demo")
    print("=" * 50)
    print(f"{'Ratio':>8}  {'Measured':>10}  {'Error':>8}")
    print("-" * 32)
    for ratio in [2, 4, 8, 16, 4.5, 8.25]:
        div = CDRDivider(ratio=ratio)
        n = int(ratio * 10000)
        wave = div.run(n)
        measured = _measure_ratio(wave)
        err = abs(measured - ratio) / ratio * 100
        print(f"  ÷{ratio:<6}  {measured:>10.4f}  {err:>7.3f}%")


if __name__ == '__main__':
    _run_quick()
    print("\nRunning pytest...")
    pytest.main([__file__, '-v'])
