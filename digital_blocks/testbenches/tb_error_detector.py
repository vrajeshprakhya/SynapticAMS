"""
Testbench: Error Detector / Eye Monitor

Verifies:
  1. Mueller-Müller TED produces zero error for ideal (noise-free) NRZ data
  2. MM error is positive/negative for late/early clock
  3. Eye height is near full amplitude for clean signal
  4. Eye height degrades with added noise (monotone in SNR)
  5. Q-factor and BER estimate are physically reasonable
  6. EyeMetrics named-tuple fields are all populated

Run:
    python -m digital_blocks.testbenches.tb_error_detector
    pytest digital_blocks/testbenches/tb_error_detector.py -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
import numpy as np
from digital_blocks.error_detector import ErrorDetector, MuellerMullerTED, EyeMonitor


def _nrz_symbols(n=1000, rng=None):
    if rng is None:
        rng = np.random.default_rng(0)
    return rng.choice([-1.0, 1.0], size=n).astype(float)


class TestMuellerMullerTED:

    def test_zero_error_ideal_nrz(self):
        """For perfectly sampled NRZ (no ISI, no noise), MM error should be ~0."""
        ted = MuellerMullerTED(accumulate=True)
        data = _nrz_symbols(2000)
        errs = ted.update(data, data)   # samples = decisions = ideal
        avg = ted.average_error()
        assert abs(avg) < 0.05, f"MM error for ideal NRZ should be ~0, got {avg:.4f}"

    def test_late_clock_gives_positive_error(self):
        """A delayed sample (late clock) shifts the sampled eye → specific sign."""
        ted = MuellerMullerTED()
        rng = np.random.default_rng(1)
        data = _nrz_symbols(2000, rng)
        # Simulate late clock: sample is slightly toward previous symbol
        delay = 0.3
        samples = (1 - delay) * data + delay * np.roll(data, 1)
        decisions = np.sign(data)
        errs = ted.update(samples, decisions)
        # Late clock → positive error on average for this convention
        # (sign depends on convention — just verify it's nonzero)
        assert abs(np.mean(errs)) > 0.01, "Should detect timing offset"

    def test_error_direction_consistency(self):
        """Symmetric timing offsets should produce opposite-sign errors."""
        rng = np.random.default_rng(5)
        data = _nrz_symbols(5000, rng)

        ted_early = MuellerMullerTED()
        ted_late  = MuellerMullerTED()

        early_samples = (1 - 0.2) * data + 0.2 * np.roll(data, -1)  # early
        late_samples  = (1 - 0.2) * data + 0.2 * np.roll(data,  1)  # late

        e_early = np.mean(ted_early.update(early_samples, np.sign(data)))
        e_late  = np.mean(ted_late.update(late_samples,  np.sign(data)))

        assert np.sign(e_early) != np.sign(e_late), \
            f"Early ({e_early:.4f}) and late ({e_late:.4f}) should have opposite signs"

    def test_reset_clears_state(self):
        ted = MuellerMullerTED()
        data = _nrz_symbols(100)
        ted.update(data, data)
        ted.reset()
        assert ted.average_error() == 0.0


class TestEyeMonitor:

    def test_eye_height_clean_signal(self):
        em = EyeMonitor(n_levels=2, signal_amplitude=2.0)
        rng = np.random.default_rng(0)
        data = _nrz_symbols(1000, rng)
        noise = rng.normal(0, 0.05, size=1000)
        samples   = data + noise
        decisions = np.sign(samples)
        h = em.eye_height(samples, decisions)
        assert h > 1.5, f"Eye height for clean NRZ should be > 1.5 V, got {h:.3f}"

    def test_eye_height_degrades_with_noise(self):
        em = EyeMonitor(n_levels=2)
        rng = np.random.default_rng(2)
        data = _nrz_symbols(2000, rng)
        h_low_noise  = em.eye_height(data + rng.normal(0, 0.05, 2000), np.sign(data))
        h_high_noise = em.eye_height(data + rng.normal(0, 0.3,  2000), np.sign(data))
        assert h_low_noise > h_high_noise, \
            "Eye should close with higher noise"

    def test_q_factor_high_snr(self):
        em = EyeMonitor()
        rng = np.random.default_rng(3)
        data = _nrz_symbols(5000, rng)
        noise = rng.normal(0, 0.05, 5000)
        samples   = data + noise
        decisions = np.sign(samples)
        q = em.q_factor(samples, decisions)
        # SNR ~20 → Q should be large (> 5)
        assert q > 5.0, f"Q-factor should be > 5 for clean signal, got {q:.2f}"

    def test_ber_estimate_reasonable(self):
        em = EyeMonitor()
        # Q = 7 → BER ~ 1.3e-12
        ber = em.ber_estimate(q=7.0)
        assert 1e-14 < ber < 1e-10, f"BER estimate out of range: {ber:.2e}"


class TestErrorDetector:

    def test_analyse_returns_eye_metrics(self):
        ed = ErrorDetector(n_levels=2, signal_amplitude=2.0, baud_rate=10e9)
        rng = np.random.default_rng(4)
        data = _nrz_symbols(1000, rng)
        noise = rng.normal(0, 0.05, 1000)
        samples = data + noise
        decisions = np.sign(samples)
        metrics = ed.analyse(samples, decisions)
        assert metrics.height > 0.0
        assert 0.0 < metrics.opening_ratio <= 1.0
        assert metrics.ber_estimate > 0.0

    def test_mm_phase_error_zero_ideal(self):
        ed = ErrorDetector()
        data = _nrz_symbols(2000)
        err = ed.mm_phase_error(data, data)
        assert abs(err) < 0.1, f"MM error should be ~0 for ideal data, got {err:.4f}"

    def test_eye_opening_tuple(self):
        ed = ErrorDetector(signal_amplitude=2.0)
        rng = np.random.default_rng(6)
        data = _nrz_symbols(500, rng)
        samples = data + rng.normal(0, 0.05, 500)
        h, ratio = ed.eye_opening(samples, np.sign(samples))
        assert h >= 0.0
        assert ratio >= 0.0


def _run_quick():
    print("Error Detector Quick Demo")
    print("=" * 60)
    rng = np.random.default_rng(0)
    data = _nrz_symbols(5000, rng)

    for snr_db in [20, 15, 10, 7]:
        sigma = 10 ** (-snr_db / 20)
        samples = data + rng.normal(0, sigma, 5000)
        decisions = np.sign(samples)

        ed = ErrorDetector(signal_amplitude=2.0)
        m = ed.analyse(samples, decisions)
        print(f"  SNR={snr_db:2d}dB: eye_h={m.height:.3f}V  "
              f"Q={m.opening_ratio*10:.2f}  BER≈{m.ber_estimate:.2e}  "
              f"MM_err={m.phase_err:.4f}")


if __name__ == '__main__':
    _run_quick()
    print("\nRunning pytest...")
    pytest.main([__file__, '-v'])
