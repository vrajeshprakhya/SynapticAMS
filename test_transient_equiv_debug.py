#!/usr/bin/env python3
"""
Debug script to test transient equivalence checking.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from equivalence_checker_osdi import OSDIEquivalenceChecker

def main():
    print("=" * 80)
    print(" TRANSIENT EQUIVALENCE CHECKER DEBUG")
    print("=" * 80)

    # Read the SPICE netlist
    netlist_path = Path("serdes_top.cir")
    if not netlist_path.exists():
        print(f"Error: {netlist_path} not found")
        return 1

    netlist = netlist_path.read_text()

    # Read one of the generated Verilog-AMS models
    va_path = Path("output_serdes_hybrid/programmatic/rx_out_n_vs_transient.va")
    if not va_path.exists():
        print(f"Error: {va_path} not found")
        return 1

    va_code = va_path.read_text()

    print("\n[Testing Transient Equivalence Checker]")
    print(f"  SPICE netlist: {netlist_path} ({len(netlist)} chars)")
    print(f"  Verilog-AMS:   {va_path.name} ({len(va_code)} chars)")
    print()

    # Create equivalence checker
    checker = OSDIEquivalenceChecker()

    # Try to compile the Verilog-AMS to OSDI
    print("[1/3] Compiling Verilog-AMS to OSDI...")
    try:
        osdi_file = checker._compile_to_osdi(va_code, "rx_out_n_vs_transient")
        if osdi_file:
            print(f"  ✓ Compiled: {osdi_file}")
        else:
            print("  ✗ Compilation failed (returned None)")
            return 1
    except Exception as e:
        print(f"  ✗ Compilation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Try to run transient simulation on SPICE
    print("\n[2/3] Running SPICE transient simulation...")
    try:
        spice_data = checker._run_transient_spice(
            netlist,
            output_nodes=['rx_out_n'],
            tstop=10e-9,  # 10ns
            tstep=10e-12   # 10ps
        )
        if spice_data:
            print(f"  ✓ SPICE simulation succeeded")
            print(f"    Signals: {list(spice_data.keys())}")
            for sig, data in spice_data.items():
                print(f"    {sig}: {len(data)} points")
        else:
            print("  ✗ SPICE simulation failed (returned None)")
            print("  Check /tmp/spice_output.txt for errors")
            return 1
    except Exception as e:
        print(f"  ✗ SPICE simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Try to run transient simulation on OSDI
    print("\n[3/3] Running OSDI transient simulation...")
    try:
        osdi_data = checker._run_transient_osdi(
            osdi_file,
            "rx_out_n_vs_transient",
            output_nodes=['rx_out_n'],
            tstop=10e-9,
            tstep=10e-12
        )
        if osdi_data:
            print(f"  ✓ OSDI simulation succeeded")
            print(f"    Signals: {list(osdi_data.keys())}")
            for sig, data in osdi_data.items():
                print(f"    {sig}: {len(data)} points")
        else:
            print("  ✗ OSDI simulation failed (returned None)")
            return 1
    except Exception as e:
        print(f"  ✗ OSDI simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Try to compare waveforms
    print("\n[Comparison]")
    try:
        result = checker._compare_transient_waveforms(
            spice_data,
            osdi_data,
            signals=['rx_out_n']
        )
        print(f"  Passed:       {result.passed}")
        print(f"  Max abs err:  {result.max_absolute_error:.6e}")
        print(f"  Max rel err:  {result.max_relative_error:.6e}")
        print(f"  RMS error:    {result.rms_error:.6e}")
        print(f"  Correlation:  {result.correlation:.4f}")
        print(f"  Coverage:     {result.coverage_percentage:.1f}%")
    except Exception as e:
        print(f"  ✗ Comparison failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 80)
    print(" DEBUG COMPLETE")
    print("=" * 80)

    return 0

if __name__ == '__main__':
    sys.exit(main())
