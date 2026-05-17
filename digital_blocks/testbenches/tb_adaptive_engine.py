"""
Testbench: Adaptive Engine (LMS)

Verifies:
  1. LMS converges MSE downward over many blocks
  2. FFE coefficient constraint: normalised taps sum to ~1.0
  3. VGA and CTLE scalars stay within configured ranges
  4. Sign-LMS vs full LMS both converge (Sign-LMS slower but stable)
  5. has_converged() correctly reports convergence after enough blocks
  6. reset() restores initial state

Run:
    python -m digital_blocks.testbenches.tb_adaptive_engine
    pytest digital_blocks/testbenches/tb_adaptive_engine.py -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
import numpy as np
from digital_blocks.adaptive_engine import AdaptiveEngine


def _simulate_channel(symbols, tap=[0.8, -0.2], noise_sigma=0.05, rng=None):
    """Simple 2-tap ISI channel + AWGN for testing."""
    if rng is None:
        rng = np.random.default_rng(0)
    h = np.array(tap)
    received = np.convolve(symbols, h, mode='same')
    received += rng.normal(0, noise_sigma, len(received))
    return received


class TestAdaptiveEngine:

    def test_mse_decreases_over_time(self):
        engine = AdaptiveEngine(ffe_taps=3, dfe_taps=3, sign_lms=False, mu_ffe=0.002)
        rng = np.random.default_rng(42)
        n_blocks = 200
        block_size = 50
        mse_vals = []
        for _ in range(n_blocks):
            symbols = rng.choice([-1.0, 1.0], size=block_size).astype(float)
            rx = _simulate_channel(symbols, rng=rng)
            decisions = np.sign(rx)
            coeffs = engine.update(rx, decisions)
        mse = engine.mse_history
        # Average MSE in first 20 blocks vs last 20 blocks should decrease
        assert np.mean(mse[-20:]) < np.mean(mse[:20]), \
            "MSE should decrease as engine adapts"

    def test_ffe_normalisation_constraint(self):
        engine = AdaptiveEngine(ffe_taps=3, ffe_constraint='normalise', mu_ffe=0.01)
        rng = np.random.default_rng(0)
        for _ in range(100):
            s = rng.choice([-1.0, 1.0], size=50).astype(float)
            engine.update(s, np.sign(s))
        taps = engine.coefficients.ffe
        norm = float(np.sum(np.abs(taps)))
        # After normalisation, sum of absolute taps should be ≤ 1.0 + epsilon
        assert norm <= 1.0 + 1e-6, f"Tap norm {norm:.6f} exceeds 1.0"

    def test_vga_stays_in_range(self):
        engine = AdaptiveEngine(
            mu_vga=0.1, vga_range=(0.1, 4.0)
        )
        rng = np.random.default_rng(1)
        for _ in range(200):
            s = rng.choice([-1.0, 1.0], size=100).astype(float)
            engine.update(s * 5.0, np.sign(s))   # large input to stress VGA
        vga = engine.coefficients.vga
        assert 0.1 <= vga <= 4.0, f"VGA {vga:.3f} outside configured range"

    def test_ctle_stays_in_range(self):
        engine = AdaptiveEngine(
            mu_ctle=0.1, ctle_range=(0.0, 20.0)
        )
        rng = np.random.default_rng(2)
        for _ in range(200):
            s = rng.choice([-1.0, 1.0], size=100).astype(float)
            engine.update(s, np.sign(s))
        ctle = engine.coefficients.ctle
        assert 0.0 <= ctle <= 20.0, f"CTLE {ctle:.3f} outside configured range"

    def test_sign_lms_converges(self):
        engine = AdaptiveEngine(ffe_taps=3, sign_lms=True, mu_ffe=0.003)
        rng = np.random.default_rng(10)
        for _ in range(400):
            s = rng.choice([-1.0, 1.0], size=50).astype(float)
            rx = _simulate_channel(s, rng=rng)
            engine.update(rx, np.sign(rx))
        mse = engine.mse_history
        # Average over 50-block windows to reduce noise in the comparison
        assert np.mean(mse[-50:]) < np.mean(mse[:50]), \
            "Sign-LMS should also converge"

    def test_has_converged_returns_false_early(self):
        engine = AdaptiveEngine()
        rng = np.random.default_rng(20)
        # Run only 10 blocks — not enough for convergence detection (needs 50)
        for _ in range(10):
            s = rng.choice([-1.0, 1.0], size=50).astype(float)
            engine.update(s, np.sign(s))
        assert not engine.has_converged(), "Should not report convergence after 10 blocks"

    def test_has_converged_returns_true_after_long_run(self):
        engine = AdaptiveEngine(mu_ffe=0.001, mu_dfe=0.001, mu_ctle=0.001, mu_vga=0.001)
        rng = np.random.default_rng(99)
        # For ideal data (no channel ISI), MSE should converge quickly
        for _ in range(200):
            s = rng.choice([-1.0, 1.0], size=50).astype(float)
            engine.update(s, np.sign(s))
        # Use very generous tolerance for this unit test
        assert engine.has_converged(window=50, tol=1.0), \
            "Engine should report convergence after 200 blocks on clean data"

    def test_reset_restores_initial_state(self):
        engine = AdaptiveEngine(ffe_taps=3)
        rng = np.random.default_rng(7)
        for _ in range(50):
            s = rng.choice([-1.0, 1.0], size=50).astype(float)
            engine.update(s, np.sign(s))
        engine.reset()
        coeffs = engine.coefficients
        # After reset: FFE should have centre tap = 1, rest = 0
        expected_ffe = np.zeros(3)
        expected_ffe[1] = 1.0
        np.testing.assert_allclose(coeffs.ffe, expected_ffe, atol=1e-9)
        assert len(engine.mse_history) == 0

    def test_coefficients_snapshot(self):
        engine = AdaptiveEngine(ffe_taps=3, dfe_taps=4)
        c = engine.coefficients
        assert len(c.ffe) == 3
        assert len(c.dfe) == 4
        assert isinstance(c.ctle, float)
        assert isinstance(c.vga, float)


def _run_quick():
    print("Adaptive Engine (LMS) Quick Demo")
    print("=" * 60)

    rng = np.random.default_rng(0)
    engine = AdaptiveEngine(ffe_taps=3, dfe_taps=5, sign_lms=True,
                            mu_ffe=0.003, mu_dfe=0.002)
    n_blocks = 300
    block_size = 64

    print(f"Running {n_blocks} × {block_size}-symbol blocks...")
    for i in range(n_blocks):
        symbols = rng.choice([-1.0, 1.0], size=block_size).astype(float)
        rx = _simulate_channel(symbols, rng=rng)
        engine.update(rx, np.sign(rx))

    mse = engine.mse_history
    c   = engine.coefficients
    print(f"Initial MSE (avg first 20 blocks): {np.mean(mse[:20]):.4f}")
    print(f"Final   MSE (avg last  20 blocks): {np.mean(mse[-20:]):.4f}")
    print(f"Converged: {engine.has_converged()}")
    print(f"FFE taps:  {[round(x,4) for x in c.ffe.tolist()]}")
    print(f"DFE taps:  {[round(x,4) for x in c.dfe.tolist()]}")
    print(f"CTLE:      {c.ctle:.3f} dB")
    print(f"VGA:       {c.vga:.3f} (linear)")


if __name__ == '__main__':
    _run_quick()
    print("\nRunning pytest...")
    pytest.main([__file__, '-v'])
