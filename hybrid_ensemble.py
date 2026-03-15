#!/usr/bin/env python3
"""
hybrid_ensemble.py — Approach 4: Ensemble/Voting Pipeline

Runs both AI and Programmatic pipelines in parallel, compares NRMSE,
and returns the best-performing model.

Architecture:
    1. Run AI pipeline (pipeline.py)         → (va_path, nrmse)
    2. Run Programmatic pipeline (complete)  → [va_files]
    3. Compare NRMSE on test DC sweep
    4. Return winner + telemetry

Author: SynapticAMS Team
Date: 2026-03-08
"""

import hashlib
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional
import tempfile

import numpy as np

# Import both pipelines
from pipeline import run_pipeline as ai_pipeline
from ngspice_runner import NgspiceRunner, NgspiceError
from ai_agent import compute_nrmse, evaluate_va_code

# Try to import programmatic pipeline (optional)
try:
    from pipeline_ext.complete_pipeline import spice_to_verilog_ams as programmatic_pipeline
    PROGRAMMATIC_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Programmatic pipeline not available: {e}")
    print("Running in AI-only mode.")
    PROGRAMMATIC_AVAILABLE = False
    programmatic_pipeline = None


# ── Configuration ──────────────────────────────────────────────────────

DEFAULT_CACHE_DIR = Path.home() / ".synapticams_cache"
DEFAULT_NRMSE_THRESHOLD = 0.05
MAX_WORKERS = 2  # AI + Programmatic


# ── Helper Functions ───────────────────────────────────────────────────

def _hash_netlist(netlist: str) -> str:
    """Generate unique hash for netlist content."""
    return hashlib.md5(netlist.encode()).hexdigest()


def _load_cache(cache_file: Path) -> Optional[Dict[str, Any]]:
    """Load cached results if they exist and are valid."""
    if not cache_file.exists():
        return None
    try:
        with open(cache_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _save_cache(cache_file: Path, data: Dict[str, Any]):
    """Save results to cache."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'w') as f:
        json.dump(data, f, indent=2, default=str)


def _run_test_dc_sweep(netlist: str, signal_source: str, vdd: float, output_node: str):
    """
    Run a test DC sweep for validation (separate from training data).

    Uses a slightly different sweep range to ensure independent validation.
    """
    runner = NgspiceRunner()
    try:
        # Use 30 points instead of 50 (different from AI pipeline default)
        results = runner.dc_sweep(netlist, {
            "sweep_var": signal_source,
            "start": 0.0,
            "stop": vdd,
            "step": vdd / 30,
            "observe": [output_node],
        })
        x = results[signal_source]
        y = results[output_node]
        return x, y
    except NgspiceError as e:
        print(f"      ⚠ Test sweep failed: {e}")
        return None, None


# ── Pipeline Wrappers ──────────────────────────────────────────────────

def _run_ai_pipeline_safe(netlist: str, output_dir: Path, **kwargs) -> Dict[str, Any]:
    """
    Run AI pipeline and return standardized result.

    Returns:
        dict with 'va_path', 'nrmse', 'success', 'error', 'time'
    """
    start_time = time.time()
    result = {
        'pipeline': 'ai',
        'success': False,
        'va_path': None,
        'nrmse': float('inf'),
        'error': None,
        'time': 0.0,
    }

    try:
        va_path, nrmse = ai_pipeline(
            netlist,
            output_dir=str(output_dir / "ai"),
            **kwargs
        )
        result['success'] = True
        result['va_path'] = Path(va_path)
        result['nrmse'] = nrmse if nrmse is not None else float('inf')
    except Exception as e:
        result['error'] = str(e)
        print(f"      ✗ AI pipeline failed: {e}")

    result['time'] = time.time() - start_time
    return result


def _run_programmatic_pipeline_safe(netlist: str, output_dir: Path) -> Dict[str, Any]:
    """
    Run Programmatic pipeline and return standardized result.

    Returns:
        dict with 'va_files', 'nrmse', 'success', 'error', 'time'
    """
    start_time = time.time()
    result = {
        'pipeline': 'programmatic',
        'success': False,
        'va_files': [],
        'nrmse': float('inf'),
        'error': None,
        'time': 0.0,
    }

    try:
        va_files = programmatic_pipeline(
            netlist,
            output_dir=str(output_dir / "programmatic")
        )
        result['success'] = True
        result['va_files'] = [Path(f) for f in va_files]

        # For now, use the first .va file if multiple blocks exist
        va_paths = [f for f in va_files if str(f).endswith('.va')]
        result['va_path'] = va_paths[0] if va_paths else None

        # NRMSE is embedded in the fitted model metadata
        # We'll re-evaluate on test sweep below for fair comparison

    except Exception as e:
        result['error'] = str(e)
        print(f"      ✗ Programmatic pipeline failed: {e}")

    result['time'] = time.time() - start_time
    return result


def _evaluate_model_on_test_sweep(va_path: Path, x_test: np.ndarray,
                                   y_test: np.ndarray, output_node: str) -> float:
    """
    Evaluate a Verilog-AMS model on independent test sweep data.

    Returns:
        NRMSE on test data
    """
    if va_path is None or not va_path.exists():
        return float('inf')

    try:
        va_code = va_path.read_text()
        y_model = evaluate_va_code(va_code, x_test, output_node)
        nrmse = compute_nrmse(y_test, y_model)
        return nrmse
    except Exception as e:
        print(f"      ⚠ Evaluation failed for {va_path.name}: {e}")
        return float('inf')


# ── Main Ensemble Pipeline ────────────────────────────────────────────

def ensemble_pipeline(
    netlist_text: str,
    output_dir: str = ".",
    cache: bool = True,
    parallel: bool = True,
    nrmse_threshold: float = DEFAULT_NRMSE_THRESHOLD,
    ai_kwargs: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Approach 4: Run both AI and Programmatic pipelines, return the best.

    Args:
        netlist_text: SPICE netlist as string
        output_dir: Directory to save results
        cache: Enable model caching (default True)
        parallel: Run pipelines in parallel (default True)
        nrmse_threshold: NRMSE threshold for "good enough"
        ai_kwargs: Additional arguments for AI pipeline (provider, model, etc.)

    Returns:
        dict:
            - 'winner': 'ai' | 'programmatic' | 'tie' | 'both_failed'
            - 'va_path': Path to best model
            - 'va_code': Verilog-AMS code of best model
            - 'ai_nrmse': AI pipeline NRMSE on test data
            - 'prog_nrmse': Programmatic pipeline NRMSE on test data
            - 'improvement': Percentage improvement over worse pipeline
            - 'ai_result': Full AI pipeline result dict
            - 'prog_result': Full programmatic pipeline result dict
            - 'cache_hit': Whether result was from cache
            - 'telemetry': Execution timing and metadata
    """
    print("=" * 72)
    print(" HYBRID ENSEMBLE PIPELINE (Approach 4)")
    print("=" * 72)
    print(f" Strategy: Run both pipelines, compare NRMSE, return best")
    print(f" Parallel: {'Yes' if parallel else 'No'}")
    print(f" Caching:  {'Yes' if cache else 'No'}")
    print("=" * 72)

    ai_kwargs = ai_kwargs or {}
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Check cache
    cache_hit = False
    if cache:
        cache_dir = DEFAULT_CACHE_DIR
        netlist_hash = _hash_netlist(netlist_text)
        cache_file = cache_dir / f"{netlist_hash}.json"

        cached = _load_cache(cache_file)
        if cached:
            print(f"\n✓ Cache hit: {netlist_hash[:8]}")
            cached['cache_hit'] = True
            return cached

    # Parse netlist to get test sweep parameters
    from pipeline import parse_netlist
    info = parse_netlist(netlist_text)

    print(f"\n[Circuit Info]")
    print(f"  Signal source: {info['signal_source']}")
    print(f"  Output node:   {info['output_node']}")
    print(f"  Supply (Vdd):  {info['vdd']} V")

    # Run test DC sweep (independent validation data)
    print(f"\n[Test Data] Running independent DC sweep for validation...")
    x_test, y_test = _run_test_dc_sweep(
        netlist_text,
        info['signal_source'],
        info['vdd'],
        info['output_node']
    )

    if x_test is None:
        print("  ✗ Test sweep failed — will use training NRMSE from pipelines")
        use_test_sweep = False
    else:
        print(f"  ✓ {len(x_test)} test points: {info['output_node']} ∈ [{y_test.min():.3f}, {y_test.max():.3f}] V")
        use_test_sweep = True

    # Run both pipelines
    if PROGRAMMATIC_AVAILABLE:
        print(f"\n[Execution] Running both pipelines...")
    else:
        print(f"\n[Execution] Running AI pipeline only (programmatic unavailable)...")

    start_time = time.time()

    if parallel and PROGRAMMATIC_AVAILABLE:
        # Parallel execution
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            ai_future = executor.submit(
                _run_ai_pipeline_safe, netlist_text, output_path, **ai_kwargs
            )
            prog_future = executor.submit(
                _run_programmatic_pipeline_safe, netlist_text, output_path
            )

            # Wait for both
            ai_result = ai_future.result()
            prog_result = prog_future.result()
    else:
        # Sequential execution or AI-only
        ai_result = _run_ai_pipeline_safe(netlist_text, output_path, **ai_kwargs)
        if PROGRAMMATIC_AVAILABLE:
            prog_result = _run_programmatic_pipeline_safe(netlist_text, output_path)
        else:
            # Create dummy failed result for programmatic
            prog_result = {
                'pipeline': 'programmatic',
                'success': False,
                'va_files': [],
                'nrmse': float('inf'),
                'test_nrmse': float('inf'),
                'error': 'Programmatic pipeline not available',
                'time': 0.0,
            }

    total_time = time.time() - start_time

    # Evaluate on test sweep if available
    if use_test_sweep and ai_result['success']:
        ai_test_nrmse = _evaluate_model_on_test_sweep(
            ai_result['va_path'], x_test, y_test, info['output_node']
        )
        ai_result['test_nrmse'] = ai_test_nrmse
    else:
        ai_result['test_nrmse'] = ai_result['nrmse']

    if use_test_sweep and prog_result['success']:
        prog_test_nrmse = _evaluate_model_on_test_sweep(
            prog_result.get('va_path'), x_test, y_test, info['output_node']
        )
        prog_result['test_nrmse'] = prog_test_nrmse
    else:
        prog_result['test_nrmse'] = prog_result['nrmse']

    # Compare and pick winner
    print(f"\n[Results]")
    print(f"  AI Pipeline:")
    print(f"    Status:        {'✓ Success' if ai_result['success'] else '✗ Failed'}")
    if ai_result['success']:
        print(f"    Training NRMSE: {ai_result['nrmse']:.4f}")
        print(f"    Test NRMSE:     {ai_result['test_nrmse']:.4f}")
        print(f"    Time:          {ai_result['time']:.2f}s")
    else:
        print(f"    Error:         {ai_result['error']}")

    print(f"\n  Programmatic Pipeline:")
    print(f"    Status:        {'✓ Success' if prog_result['success'] else '✗ Failed'}")
    if prog_result['success']:
        print(f"    Training NRMSE: {prog_result['nrmse']:.4f}")
        print(f"    Test NRMSE:     {prog_result['test_nrmse']:.4f}")
        print(f"    Time:          {prog_result['time']:.2f}s")
        print(f"    Files:         {len(prog_result['va_files'])}")
    else:
        print(f"    Error:         {prog_result['error']}")

    # Determine winner
    ai_nrmse = ai_result['test_nrmse']
    prog_nrmse = prog_result['test_nrmse']

    if not ai_result['success'] and not prog_result['success']:
        winner = 'both_failed'
        best_va_path = None
        best_va_code = None
        improvement = 0.0
    elif not ai_result['success']:
        winner = 'programmatic'
        best_va_path = prog_result.get('va_path')
        improvement = 100.0  # Only option that worked
    elif not prog_result['success']:
        winner = 'ai'
        best_va_path = ai_result['va_path']
        improvement = 100.0  # Only option that worked
    else:
        # Both succeeded — compare NRMSE
        if abs(ai_nrmse - prog_nrmse) < 0.001:  # Essentially tied
            winner = 'tie'
            best_va_path = ai_result['va_path']  # Prefer AI for readability
            improvement = 0.0
        elif ai_nrmse < prog_nrmse:
            winner = 'ai'
            best_va_path = ai_result['va_path']
            improvement = ((prog_nrmse - ai_nrmse) / prog_nrmse) * 100
        else:
            winner = 'programmatic'
            best_va_path = prog_result.get('va_path')
            improvement = ((ai_nrmse - prog_nrmse) / ai_nrmse) * 100

    # Load winning code
    best_va_code = None
    if best_va_path and best_va_path.exists():
        best_va_code = best_va_path.read_text()

    # Build result
    result = {
        'winner': winner,
        'va_path': best_va_path,
        'va_code': best_va_code,
        'ai_nrmse': ai_nrmse,
        'prog_nrmse': prog_nrmse,
        'improvement': improvement,
        'ai_result': ai_result,
        'prog_result': prog_result,
        'cache_hit': cache_hit,
        'telemetry': {
            'total_time': total_time,
            'ai_time': ai_result['time'],
            'prog_time': prog_result['time'],
            'parallel': parallel,
            'test_sweep_points': len(x_test) if x_test is not None else 0,
        }
    }

    # Print summary
    print(f"\n{'=' * 72}")
    print(f" WINNER: {winner.upper()}")
    if winner not in ('both_failed', 'tie'):
        print(f" Improvement: {improvement:.1f}% better than {'programmatic' if winner == 'ai' else 'AI'}")
    print(f" Best NRMSE: {min(ai_nrmse, prog_nrmse):.4f}")
    print(f" Total time: {total_time:.2f}s")
    if parallel:
        speedup = (ai_result['time'] + prog_result['time']) / total_time
        print(f" Speedup:    {speedup:.2f}x (parallel execution)")
    print(f"={'=' * 72}")

    # Save to cache
    if cache and winner != 'both_failed':
        cache_data = {
            'winner': winner,
            'ai_nrmse': float(ai_nrmse),
            'prog_nrmse': float(prog_nrmse),
            'improvement': float(improvement),
            'timestamp': time.time(),
        }
        _save_cache(cache_file, cache_data)
        print(f"\n✓ Cached result: {netlist_hash[:8]}")

    return result


# ── Command-line Interface ─────────────────────────────────────────────

if __name__ == "__main__":
    # Example: Common-source NMOS amplifier
    NETLIST = """
* Common-source NMOS amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 5
Vin vin 0 DC 0
.MODEL NMOS NMOS (VTO=0.7 KP=100u)
.DC Vin 0 5 0.1
.END
"""

    result = ensemble_pipeline(
        NETLIST,
        output_dir="/tmp/hybrid_test",
        cache=True,
        parallel=True,
    )

    print(f"\n{'=' * 72}")
    print(" RESULT SUMMARY")
    print(f"{'=' * 72}")
    print(f"Winner:      {result['winner']}")
    print(f"Best model:  {result['va_path']}")
    print(f"AI NRMSE:    {result['ai_nrmse']:.4f}")
    print(f"Prog NRMSE:  {result['prog_nrmse']:.4f}")
    print(f"Improvement: {result['improvement']:.1f}%")
    print(f"{'=' * 72}")
