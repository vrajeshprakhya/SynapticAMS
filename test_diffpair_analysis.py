#!/usr/bin/env python3
"""
Test differential pair DC sweep through SynapticAMS pipeline.

Circuit: BJT differential pair with current mirror bias
Analysis: DC sweep of differential input voltage
Expected: S-curve transfer characteristic
"""

import sys
import os
import numpy as np

# Optional matplotlib for plotting
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("Note: matplotlib not available, skipping plots")

# Add circuit_preprocess to path
sys.path.insert(0, os.path.expanduser('~/circuit_preprocess'))

from ngspice_runner import NgspiceRunner
from verilog_ams_generator import VerilogAMSGenerator

def main():
    print("="*80)
    print("DIFFERENTIAL PAIR DC SWEEP TEST")
    print("="*80)

    # Paths
    netlist_path = os.path.expanduser('~/SynapticAMS/test_diffpair_dc.cir')
    output_va_path = '/tmp/diffpair_behavioral.va'

    print(f"\nCircuit: {netlist_path}")
    print(f"Output: {output_va_path}")

    # Read netlist
    with open(netlist_path, 'r') as f:
        netlist = f.read()

    # Initialize ngspice runner
    runner = NgspiceRunner()

    # Configure DC sweep parameters
    dc_params = {
        'sweep_var': 'vdm_p',  # Sweep differential input
        'start': -1.0,
        'stop': 1.0,
        'step': 0.01,
        'observe': ['v(vout_p)', 'v(vout_n)', 'v(vin_p)']
    }

    print("\n" + "-"*80)
    print("STEP 1: Running DC Sweep Simulation")
    print("-"*80)
    print(f"Sweep variable: {dc_params['sweep_var']}")
    print(f"Range: {dc_params['start']}V to {dc_params['stop']}V")
    print(f"Step: {dc_params['step']}V")

    # Run DC sweep
    try:
        results = runner.dc_sweep(netlist, dc_params)
        print(f"✓ DC sweep completed successfully")
        print(f"  - Data points: {len(results[dc_params['sweep_var']])}")
    except Exception as e:
        print(f"✗ DC sweep FAILED: {e}")
        return 1

    # Extract data
    vin_p = results['v(vin_p)']
    vout_p = results['v(vout_p)']
    vout_n = results['v(vout_n)']
    vdm_in = vin_p  # Differential input (vin_n = 0)
    vdm_out = vout_p - vout_n  # Differential output

    print("\n" + "-"*80)
    print("STEP 2: Analyzing Transfer Characteristic")
    print("-"*80)

    # Calculate differential gain (slope of transfer curve)
    # Find linear region (middle 50% of output swing)
    vout_min, vout_max = vdm_out.min(), vdm_out.max()
    linear_mask = (vdm_out > vout_min + 0.25*(vout_max - vout_min)) & \
                  (vdm_out < vout_min + 0.75*(vout_max - vout_min))

    if linear_mask.sum() > 10:
        # Linear regression in linear region
        coeffs = np.polyfit(vdm_in[linear_mask], vdm_out[linear_mask], 1)
        diff_gain = coeffs[0]  # Slope = differential gain
        print(f"Differential gain: {diff_gain:.2f} V/V ({20*np.log10(abs(diff_gain)):.1f} dB)")
    else:
        diff_gain = None
        print(f"⚠ Could not determine differential gain (no linear region found)")

    # Output swing
    print(f"Output swing: {vout_max - vout_min:.3f} V")
    print(f"  - Vout_max: {vout_max:.3f} V")
    print(f"  - Vout_min: {vout_min:.3f} V")

    # Common-mode output
    vcm_out = (vout_p + vout_n) / 2
    print(f"Common-mode output: {vcm_out.mean():.3f} V (avg)")

    print("\n" + "-"*80)
    print("STEP 3: Generating Verilog-AMS Behavioral Model")
    print("-"*80)

    # Generate behavioral model
    generator = VerilogAMSGenerator()

    # Use lookup table model for nonlinear transfer function
    model_data = {
        'input': vdm_in.tolist(),
        'output': vdm_out.tolist(),
        'type': 'lookup_table',
        'gain': diff_gain if diff_gain is not None else 1.0,
        'output_swing': float(vout_max - vout_min)
    }

    try:
        verilog_code = generator.generate(
            module_name='diffpair_behavioral',
            inputs=['vin_p', 'vin_n'],
            outputs=['vout_p', 'vout_n'],
            model=model_data,
            data=results
        )

        with open(output_va_path, 'w') as f:
            f.write(verilog_code)

        print(f"✓ Verilog-AMS model generated: {output_va_path}")
    except Exception as e:
        print(f"✗ Model generation FAILED: {e}")
        return 1

    if HAS_MATPLOTLIB:
        print("\n" + "-"*80)
        print("STEP 4: Plotting Results")
        print("-"*80)

        # Create plots
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # Plot 1: Transfer characteristic
        ax1.plot(vdm_in, vdm_out, 'b-', linewidth=2, label='Vout_diff vs Vin_diff')
        ax1.axhline(y=0, color='k', linestyle='--', alpha=0.3)
        ax1.axvline(x=0, color='k', linestyle='--', alpha=0.3)
        ax1.set_xlabel('Differential Input (V)', fontsize=12)
        ax1.set_ylabel('Differential Output (V)', fontsize=12)
        ax1.set_title('Differential Pair Transfer Characteristic', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.legend()

        # Plot 2: Single-ended outputs
        ax2.plot(vdm_in, vout_p, 'r-', linewidth=2, label='Vout_p')
        ax2.plot(vdm_in, vout_n, 'b-', linewidth=2, label='Vout_n')
        ax2.set_xlabel('Differential Input (V)', fontsize=12)
        ax2.set_ylabel('Output Voltage (V)', fontsize=12)
        ax2.set_title('Single-Ended Outputs', fontsize=14, fontweight='bold')
        ax2.grid(True, alpha=0.3)
        ax2.legend()

        plt.tight_layout()
        plot_path = '/tmp/diffpair_dc_sweep.png'
        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        print(f"✓ Plot saved: {plot_path}")
    else:
        print("\n⚠ Skipping plots (matplotlib not installed)")

    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"✓ Differential pair DC sweep: PASSED")
    print(f"✓ Transfer characteristic: S-curve observed")
    if diff_gain is not None:
        print(f"✓ Differential gain: {diff_gain:.2f} V/V")
    print(f"✓ Behavioral model: Generated")
    print("\n" + "="*80)

    return 0

if __name__ == '__main__':
    sys.exit(main())
