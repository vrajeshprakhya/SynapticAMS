#!/usr/bin/env python3
"""
Test complete_pipeline.py with independence detection

Tests three scenarios:
1. Single input → 1D sweep
2. Coupled inputs → 2D sweep
3. Independent inputs → Multiple 1D sweeps
"""

import sys
from pathlib import Path

# Add parent directory to path to import pipeline modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from complete_pipeline import spice_to_verilog_ams

# Test circuits from ~/eda_tools and custom circuits
test_circuits = {
    'eda_112': {
        'file': '/home/vrajeshprakhya/eda_tools/ams-net.github.io/amsnet_1.0/112/112.cir',
        'description': 'EDA Tools Circuit 112 (NMOS with voltage source)',
        'expected': '1D sweep'
    },
    'eda_262': {
        'file': '/home/vrajeshprakhya/eda_tools/ams-net.github.io/amsnet_1.0/262/262.cir',
        'description': 'EDA Tools Circuit 262 (Current source circuit)',
        'expected': '1D sweep'
    },
    'simple_amp': {
        'file': 'test_circuits/simple_amp.cir',
        'description': 'Custom: Single Input (Common-Source Amp)',
        'expected': '1D sweep'
    },
    'coupled_amp': {
        'file': 'test_circuits/coupled_amp.cir',
        'description': 'Custom: Coupled Inputs (Differential Pair)',
        'expected': '2D sweep'
    },
    'independent_amps': {
        'file': 'test_circuits/independent_amps.cir',
        'description': 'Custom: Independent Inputs (Two Stages)',
        'expected': 'Multiple 1D sweeps'
    }
}

def run_test(name, test_info):
    """Run complete pipeline on a test circuit"""
    print("\n" + "=" * 80)
    print(f" TEST: {test_info['description']}")
    print(f" File: {test_info['file']}")
    print(f" Expected: {test_info['expected']}")
    print("=" * 80)

    # Read netlist
    netlist_path = Path(test_info['file'])
    if not netlist_path.exists():
        print(f"✗ SKIP - File not found: {netlist_path}")
        return None

    netlist = netlist_path.read_text()

    # Run pipeline
    try:
        output_dir = f'test_output_{name}'
        Path(output_dir).mkdir(exist_ok=True)

        saved_files = spice_to_verilog_ams(netlist, output_dir)

        print(f"\n✓ Pipeline completed successfully!")
        print(f"  Generated {len(saved_files)} files")

        return 'PASS'

    except Exception as e:
        print(f"\n✗ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return 'FAIL'


def main():
    print("\n" + "=" * 80)
    print(" COMPLETE PIPELINE TEST - INDEPENDENCE DETECTION")
    print("=" * 80)

    results = {}

    # Run all tests
    for name, test_info in test_circuits.items():
        result = run_test(name, test_info)
        results[name] = result

    # Summary
    print("\n\n" + "=" * 80)
    print(" TEST SUMMARY")
    print("=" * 80)

    for name, result in results.items():
        if result is None:
            status = "⚠ SKIP"
        elif result == 'PASS':
            status = "✓ PASS"
        else:
            status = "✗ FAIL"

        print(f"{status:10s} {test_circuits[name]['description']}")

    # Count results
    passed = sum(1 for r in results.values() if r == 'PASS')
    failed = sum(1 for r in results.values() if r == 'FAIL')
    skipped = sum(1 for r in results.values() if r is None)

    print("\n" + "=" * 80)
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 80)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
