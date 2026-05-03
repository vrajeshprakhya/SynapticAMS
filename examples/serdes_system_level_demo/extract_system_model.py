#!/usr/bin/env python3
"""
Extract a single system-level behavioral model from SerDes netlist
Bypasses automatic block discovery to extract only final_out = f(tx_p_src, tx_n_src)
"""

import sys
import numpy as np
from pathlib import Path

# Import pipeline components
from ngspice_runner import NgspiceRunner
from pipeline_ext.fit_transfer_function import fit_transfer_function, fit_transfer_function_2d
from pipeline_ext.verilog_ams_generator import VerilogAMSGenerator

def extract_system_level_model(netlist_path, output_dir):
    """
    Extract ONE system-level model: final_out = f(tx_p_src, tx_n_src)

    Manually specifies inputs and outputs instead of using block discovery.
    """
    print("="*70)
    print(" SYSTEM-LEVEL MODEL EXTRACTION")
    print("="*70)
    print(f"\nInput netlist: {netlist_path}")
    print(f"Output directory: {output_dir}")

    # Read netlist
    netlist_text = Path(netlist_path).read_text()

    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # System-level I/O specification (manual, not auto-discovered)
    print("\n[1/4] System I/O specification:")
    print("  Inputs:  tx_p_src, tx_n_src (differential)")
    print("  Output:  final_out")

    # Run 2D DC sweep: sweep both inputs
    print("\n[2/4] Running 2D DC sweep...")
    runner = NgspiceRunner()

    sweep_plan = {
        'type': 'dc_sweep_2d',
        'sweep_var_1': 'tx_p_src',
        'sweep_var_2': 'tx_n_src',
        'start_1': 0.0,
        'stop_1': 1.8,
        'step_1': 0.2,  # 10 points
        'start_2': 0.0,
        'stop_2': 1.8,
        'step_2': 0.2,  # 10 points
        'observe': ['final_out']
    }

    print(f"  {sweep_plan['sweep_var_1']}: [{sweep_plan['start_1']} → {sweep_plan['stop_1']}] step {sweep_plan['step_1']}")
    print(f"  {sweep_plan['sweep_var_2']}: [{sweep_plan['start_2']} → {sweep_plan['stop_2']}] step {sweep_plan['step_2']}")
    print(f"  Observe: {sweep_plan['observe']}")

    try:
        results = runner.dc_sweep_2d(netlist_text, sweep_plan)

        x1 = results['tx_p_src']
        x2 = results['tx_n_src']
        z = results['final_out']

        print(f"  ✓ Completed: {len(x1)}×{len(x2)} grid = {len(x1)*len(x2)} points")

    except Exception as e:
        print(f"  ✗ 2D sweep failed: {e}")
        print("\n  Falling back to 1D sweep (single input)...")

        # Fallback: 1D sweep on first input only
        sweep_plan_1d = {
            'sweep_var': 'tx_p_src',
            'start': 0.0,
            'stop': 1.8,
            'step': 0.05,  # 37 points
            'observe': ['final_out']
        }

        try:
            results_1d = runner.dc_sweep(netlist_text, sweep_plan_1d)
            x1 = results_1d['tx_p_src']
            z = results_1d['final_out']
            x2 = None  # Single input only

            print(f"  ✓ Completed: {len(x1)} points")

        except Exception as e:
            print(f"  ✗ 1D sweep also failed: {e}")
            sys.exit(1)

    # Fit transfer function
    print("\n[3/4] Fitting transfer function...")

    if x2 is not None:
        # 2D model
        print(f"  final_out = f(tx_p_src, tx_n_src)")

        # Reshape if needed
        if z.ndim == 1:
            expected_shape = (len(x1), len(x2))
            if len(z) == len(x1) * len(x2):
                z = z.reshape(expected_shape)

        model = fit_transfer_function_2d(x1, x2, z)

        print(f"  Model type: {model['model_type']}")
        print(f"  Intent: {model['intent']}")

        fitted_model = {
            'input': ['tx_p_src', 'tx_n_src'],
            'output': 'final_out',
            'model': model,
            'data': {'x1': x1, 'x2': x2, 'z': z}
        }

    else:
        # 1D model
        print(f"  final_out = f(tx_p_src)")

        model = fit_transfer_function(x1, z)

        print(f"  Model type: {model['model_type']}")
        print(f"  Intent: {model['intent']}")

        fitted_model = {
            'input': 'tx_p_src',
            'output': 'final_out',
            'model': model,
            'data': {'x': x1, 'y': z}
        }

    # Generate Verilog-AMS
    print("\n[4/4] Generating Verilog-AMS...")
    generator = VerilogAMSGenerator()

    module_name = "serdes_rx_system"
    code = generator.generate_module(fitted_model, module_name=module_name)

    # Save to file
    output_path = Path(output_dir) / f"{module_name}.va"
    output_path.write_text(code)

    print(f"  ✓ Generated: {module_name}")
    print(f"  Saved to: {output_path}")

    # Show module header
    for line in code.split('\n')[:15]:
        print(f"    {line}")

    print("\n" + "="*70)
    print(" EXTRACTION COMPLETE!")
    print("="*70)
    print(f"\nGenerated 1 system-level behavioral model:")
    print(f"  {output_path}")

    return str(output_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 extract_system_model.py <netlist.cir> [output_dir]")
        sys.exit(1)

    netlist_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/serdes_system_model"

    va_file = extract_system_level_model(netlist_path, output_dir)

    print(f"\nNext steps:")
    print(f"  1. View model: cat {va_file}")
    print(f"  2. Compile: openvaf {va_file}")
    print(f"  3. Validate with AI refinement pipeline")
