#!/usr/bin/env python3
"""
Test transient analysis with oscillator circuits

Tests the complete transient analysis pipeline:
1. Run transient simulation on oscillator circuit
2. Extract oscillation frequency using multiple methods
3. Characterize oscillator (frequency, amplitude, waveform type)
4. Generate Verilog-AMS oscillator model
5. Validate results
"""

import numpy as np
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from ngspice_runner import NgspiceRunner
from transient_analysis_utils import (
    extract_oscillation_frequency,
    characterize_oscillator,
    detect_oscillation,
    measure_amplitude
)
from pipeline_ext.verilog_ams_generator import VerilogAMSGenerator


def test_lc_oscillator():
    """Test LC tank oscillator"""
    print("=" * 72)
    print(" TEST 1: LC TANK OSCILLATOR")
    print("=" * 72)

    # Read netlist
    netlist_path = Path("test_oscillator_lc.cir")
    netlist = netlist_path.read_text()

    print(f"\nNetlist: {netlist_path}")
    print(f"Expected frequency: ~500 MHz (LC resonance)")

    # Run transient analysis
    print("\nRunning transient simulation...")
    runner = NgspiceRunner()

    tran_params = {
        'tstep': 10e-12,     # 10 ps output step
        'tstop': 20e-9,      # 20 ns total
        'tstart': 0,
        'uic': True,         # Use initial conditions
        'observe': ['vout']
    }

    try:
        result = runner.transient_analysis(netlist, tran_params)

        time = result['time']
        voltage = result['vout']

        print(f"  Simulation points: {len(time)}")
        print(f"  Time range: {time[0]*1e9:.3f} ns to {time[-1]*1e9:.3f} ns")
        print(f"  Voltage range: {voltage.min():.3f} V to {voltage.max():.3f} V")

        # Skip initial transient (first 20% of data)
        skip = int(len(time) * 0.2)
        time_steady = time[skip:]
        voltage_steady = voltage[skip:]

        # Check if oscillating
        print("\n--- Oscillation Detection ---")
        is_oscillating = detect_oscillation(time_steady, voltage_steady)
        print(f"  Is oscillating: {is_oscillating}")

        if not is_oscillating:
            print("  ✗ Circuit not oscillating!")
            return False

        # Extract frequency using different methods
        print("\n--- Frequency Extraction ---")
        freq_zc = extract_oscillation_frequency(time_steady, voltage_steady, 'zero_crossing')
        freq_fft = extract_oscillation_frequency(time_steady, voltage_steady, 'fft')
        freq_ac = extract_oscillation_frequency(time_steady, voltage_steady, 'autocorrelation')

        print(f"  Zero-crossing: {freq_zc/1e6:.2f} MHz" if freq_zc else "  Zero-crossing: Failed")
        print(f"  FFT:           {freq_fft/1e6:.2f} MHz" if freq_fft else "  FFT: Failed")
        print(f"  Autocorr:      {freq_ac/1e6:.2f} MHz" if freq_ac else "  Autocorr: Failed")

        # Full characterization
        print("\n--- Full Characterization ---")
        char = characterize_oscillator(time_steady, voltage_steady, skip_transient=0.0)

        print(f"  Frequency:      {char['frequency']/1e6:.2f} MHz")
        print(f"  Period:         {char['period']*1e9:.3f} ns")
        print(f"  Amplitude:      {char['amplitude']:.3f} V (peak-to-peak)")
        print(f"  DC offset:      {char['dc_offset']:.3f} V")
        print(f"  Waveform type:  {char['waveform_type']}")

        # Generate Verilog-AMS model
        print("\n--- Verilog-AMS Generation ---")
        generator = VerilogAMSGenerator()

        model_info = {
            'model_type': 'oscillator',
            'frequency': char['frequency'],
            'amplitude': char['amplitude'],
            'dc_offset': char['dc_offset'],
            'waveform_type': char['waveform_type'],
            'intent': 'oscillator'
        }

        code = generator._generate_oscillator_module(
            'lc_oscillator', 'vout', model_info, {}
        )

        print("Generated Verilog-AMS module:")
        print("-" * 72)
        print(code)
        print("-" * 72)

        # Save to file
        output_file = Path("/tmp/lc_oscillator.va")
        output_file.write_text(code)
        print(f"\nSaved to: {output_file}")

        print("\n✓ LC oscillator test passed!")
        return True

    except Exception as e:
        print(f"\n✗ LC oscillator test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ring_oscillator():
    """Test ring oscillator (3-stage inverter)"""
    print("\n\n" + "=" * 72)
    print(" TEST 2: RING OSCILLATOR (3-STAGE)")
    print("=" * 72)

    # Read netlist
    netlist_path = Path("test_oscillator_ring.cir")
    netlist = netlist_path.read_text()

    print(f"\nNetlist: {netlist_path}")
    print(f"Expected frequency: ~1-2 GHz")

    # Run transient analysis
    print("\nRunning transient simulation...")
    runner = NgspiceRunner()

    tran_params = {
        'tstep': 10e-12,     # 10 ps output step
        'tstop': 12e-9,      # 12 ns total
        'tstart': 0,
        'uic': True,         # Use initial conditions
        'observe': ['vin', 'v1', 'v2']
    }

    try:
        result = runner.transient_analysis(netlist, tran_params)

        time = result['time']
        voltage = result['vin']  # Monitor feedback node

        print(f"  Simulation points: {len(time)}")
        print(f"  Time range: {time[0]*1e9:.3f} ns to {time[-1]*1e9:.3f} ns")
        print(f"  Voltage range: {voltage.min():.3f} V to {voltage.max():.3f} V")

        # Skip initial transient (first 30% of data for ring osc startup)
        skip = int(len(time) * 0.3)
        time_steady = time[skip:]
        voltage_steady = voltage[skip:]

        # Check if oscillating
        print("\n--- Oscillation Detection ---")
        is_oscillating = detect_oscillation(time_steady, voltage_steady)
        print(f"  Is oscillating: {is_oscillating}")

        if not is_oscillating:
            print("  ✗ Circuit not oscillating!")
            return False

        # Extract frequency
        print("\n--- Frequency Extraction ---")
        freq_zc = extract_oscillation_frequency(time_steady, voltage_steady, 'zero_crossing')
        freq_fft = extract_oscillation_frequency(time_steady, voltage_steady, 'fft')

        print(f"  Zero-crossing: {freq_zc/1e9:.2f} GHz" if freq_zc else "  Zero-crossing: Failed")
        print(f"  FFT:           {freq_fft/1e9:.2f} GHz" if freq_fft else "  FFT: Failed")

        # Full characterization
        print("\n--- Full Characterization ---")
        char = characterize_oscillator(time_steady, voltage_steady, skip_transient=0.0)

        print(f"  Frequency:      {char['frequency']/1e9:.3f} GHz")
        print(f"  Period:         {char['period']*1e12:.2f} ps")
        print(f"  Amplitude:      {char['amplitude']:.3f} V (peak-to-peak)")
        print(f"  DC offset:      {char['dc_offset']:.3f} V")
        print(f"  Waveform type:  {char['waveform_type']}")

        # Generate Verilog-AMS model
        print("\n--- Verilog-AMS Generation ---")
        generator = VerilogAMSGenerator()

        model_info = {
            'model_type': 'oscillator',
            'frequency': char['frequency'],
            'amplitude': char['amplitude'],
            'dc_offset': char['dc_offset'],
            'waveform_type': char['waveform_type'],
            'intent': 'oscillator'
        }

        code = generator._generate_oscillator_module(
            'ring_oscillator', 'vin', model_info, {}
        )

        print("Generated Verilog-AMS module:")
        print("-" * 72)
        # Only print first 30 lines for brevity
        lines = code.split('\n')
        print('\n'.join(lines[:30]))
        if len(lines) > 30:
            print("... (truncated)")
        print("-" * 72)

        # Save to file
        output_file = Path("/tmp/ring_oscillator.va")
        output_file.write_text(code)
        print(f"\nSaved to: {output_file}")

        print("\n✓ Ring oscillator test passed!")
        return True

    except Exception as e:
        print(f"\n✗ Ring oscillator test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all oscillator tests"""
    print("\n" + "=" * 72)
    print(" TRANSIENT ANALYSIS & OSCILLATOR CHARACTERIZATION TEST SUITE")
    print("=" * 72)

    results = []

    # Test 1: LC oscillator
    results.append(("LC Oscillator", test_lc_oscillator()))

    # Test 2: Ring oscillator
    results.append(("Ring Oscillator", test_ring_oscillator()))

    # Summary
    print("\n\n" + "=" * 72)
    print(" TEST SUMMARY")
    print("=" * 72)

    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")

    total = len(results)
    passed = sum(1 for _, p in results if p)

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n✓ All tests passed!")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
