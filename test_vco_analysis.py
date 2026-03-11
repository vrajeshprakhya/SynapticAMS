#!/usr/bin/env python3
"""
Test VCO from ngspice examples with transient analysis pipeline

Tests:
1. Run transient simulation on 7-stage differential ring oscillator VCO
2. Extract oscillation frequency using multiple methods
3. Characterize oscillator (frequency, amplitude, waveform type)
4. Generate Verilog-AMS behavioral model
5. Validate against expected VCO specifications
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


def test_vco():
    """Test ngspice VCO (7-stage differential ring oscillator)"""
    print("=" * 72)
    print(" VCO TRANSIENT ANALYSIS TEST")
    print(" 7-Stage Differential Ring Oscillator (BSIM3)")
    print("=" * 72)

    # Read netlist
    netlist_path = Path("test_vco_ngspice.cir")
    if not netlist_path.exists():
        print(f"\n✗ Error: {netlist_path} not found!")
        return False

    netlist = netlist_path.read_text()

    print(f"\nNetlist: {netlist_path}")
    print(f"Control Voltage: 1.5V (mid-range)")
    print(f"Expected frequency: ~500 MHz")
    print(f"Technology: BSIM3 (350nm CMOS)")

    # Run transient analysis
    print("\nRunning transient simulation...")
    runner = NgspiceRunner()

    tran_params = {
        'tstep': 20e-12,     # 20 ps output step
        'tstop': 40e-9,      # 40 ns total (~20 cycles at 500 MHz)
        'tstart': 0,
        'observe': ['aout']   # Analog output from VCO
    }

    try:
        result = runner.transient_analysis(netlist, tran_params)

        time = result['time']
        voltage = result['aout']

        print(f"  ✓ Simulation completed successfully")
        print(f"  Simulation points: {len(time)}")
        print(f"  Time range: {time[0]*1e9:.3f} ns to {time[-1]*1e9:.3f} ns")
        print(f"  Voltage range: {voltage.min():.3f} V to {voltage.max():.3f} V")

        # Skip initial transient (first 25% of data for VCO startup)
        skip = int(len(time) * 0.25)
        time_steady = time[skip:]
        voltage_steady = voltage[skip:]

        print(f"\n  Skipping startup transient: first {skip} points ({time[skip]*1e9:.2f} ns)")
        print(f"  Analyzing steady-state: {len(time_steady)} points")

        # Check if oscillating
        print("\n" + "-" * 72)
        print(" OSCILLATION DETECTION")
        print("-" * 72)

        is_oscillating = detect_oscillation(time_steady, voltage_steady, min_cycles=5)

        if is_oscillating:
            print(f"  ✓ Circuit is oscillating")
        else:
            print(f"  ✗ Circuit NOT oscillating!")
            print(f"\n  Debugging info:")
            amp = measure_amplitude(voltage_steady, 'peak_to_peak')
            print(f"    Amplitude: {amp:.3f} V")
            print(f"    Min voltage: {voltage_steady.min():.3f} V")
            print(f"    Max voltage: {voltage_steady.max():.3f} V")
            print(f"    Mean voltage: {voltage_steady.mean():.3f} V")
            return False

        # Extract frequency using different methods
        print("\n" + "-" * 72)
        print(" FREQUENCY EXTRACTION")
        print("-" * 72)

        freq_zc = extract_oscillation_frequency(time_steady, voltage_steady, 'zero_crossing')
        freq_fft = extract_oscillation_frequency(time_steady, voltage_steady, 'fft')
        freq_ac = extract_oscillation_frequency(time_steady, voltage_steady, 'autocorrelation')

        if freq_zc:
            print(f"  Zero-crossing:   {freq_zc/1e6:>8.2f} MHz")
        else:
            print(f"  Zero-crossing:   Failed")

        if freq_fft:
            print(f"  FFT:             {freq_fft/1e6:>8.2f} MHz")
        else:
            print(f"  FFT:             Failed")

        if freq_ac:
            print(f"  Autocorrelation: {freq_ac/1e6:>8.2f} MHz")
        else:
            print(f"  Autocorrelation: Failed")

        # Full characterization
        print("\n" + "-" * 72)
        print(" OSCILLATOR CHARACTERIZATION")
        print("-" * 72)

        char = characterize_oscillator(time_steady, voltage_steady, skip_transient=0.0)

        if not char['is_oscillating']:
            print("  ✗ Characterization failed - not oscillating")
            return False

        print(f"  Frequency:       {char['frequency']/1e6:>8.2f} MHz")
        print(f"  Period:          {char['period']*1e9:>8.3f} ns")
        print(f"  Amplitude:       {char['amplitude']:>8.3f} V (peak-to-peak)")
        print(f"  DC offset:       {char['dc_offset']:>8.3f} V")
        print(f"  Waveform type:   {char['waveform_type']}")

        # Validate against expected specifications
        print("\n" + "-" * 72)
        print(" VALIDATION")
        print("-" * 72)

        expected_freq_min = 150e6  # 150 MHz
        expected_freq_max = 900e6  # 900 MHz
        expected_freq_nominal = 500e6  # 500 MHz at Vcont=1.5V

        freq = char['frequency']

        # Check frequency is in valid range
        if expected_freq_min <= freq <= expected_freq_max:
            print(f"  ✓ Frequency in spec: {freq/1e6:.1f} MHz (range: 150-900 MHz)")
        else:
            print(f"  ✗ Frequency out of spec: {freq/1e6:.1f} MHz")

        # Check frequency is close to nominal (within 50%)
        freq_error = abs(freq - expected_freq_nominal) / expected_freq_nominal * 100
        if freq_error < 50:
            print(f"  ✓ Frequency near nominal: {freq_error:.1f}% error")
        else:
            print(f"  ⚠ Frequency differs from nominal: {freq_error:.1f}% error")

        # Check amplitude is reasonable (supply rail is 3.3V)
        if 0.5 < char['amplitude'] < 3.5:
            print(f"  ✓ Amplitude reasonable: {char['amplitude']:.2f} V")
        else:
            print(f"  ⚠ Amplitude unusual: {char['amplitude']:.2f} V")

        # Generate Verilog-AMS model
        print("\n" + "-" * 72)
        print(" VERILOG-AMS BEHAVIORAL MODEL GENERATION")
        print("-" * 72)

        generator = VerilogAMSGenerator()

        model_info = {
            'model_type': 'oscillator',
            'frequency': char['frequency'],
            'amplitude': char['amplitude'],
            'dc_offset': char['dc_offset'],
            'waveform_type': char['waveform_type'],
            'intent': 'vco_behavioral_model'
        }

        code = generator._generate_oscillator_module(
            'vco_behavioral', 'aout', model_info, {}
        )

        print("Generated Verilog-AMS module:")
        print()
        # Print first 40 lines
        lines = code.split('\n')
        for line in lines[:40]:
            print(line)
        if len(lines) > 40:
            print("... (truncated)")

        # Save to file
        output_file = Path("/tmp/vco_behavioral.va")
        output_file.write_text(code)
        print(f"\n  ✓ Saved to: {output_file}")

        # Summary
        print("\n" + "=" * 72)
        print(" TEST SUMMARY")
        print("=" * 72)
        print(f"  ✓ VCO oscillating at {char['frequency']/1e6:.1f} MHz")
        print(f"  ✓ Amplitude: {char['amplitude']:.2f} V")
        print(f"  ✓ Behavioral model generated")
        print(f"\n  SUCCESS: VCO transient analysis completed!")

        return True

    except Exception as e:
        print(f"\n✗ VCO test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run VCO analysis"""
    print("\n" + "=" * 72)
    print(" NGSPICE VCO TRANSIENT ANALYSIS TEST SUITE")
    print(" Testing 7-Stage Differential Ring Oscillator")
    print("=" * 72)

    success = test_vco()

    print("\n" + "=" * 72)
    if success:
        print(" ✓ TEST PASSED")
        return 0
    else:
        print(" ✗ TEST FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
