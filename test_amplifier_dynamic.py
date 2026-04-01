#!/usr/bin/env python3
"""
Test dynamic fitting on simple amplifier
"""
from pipeline_ext.complete_pipeline import spice_to_verilog_ams

# Simple BJT amplifier (common emitter)
amplifier_netlist = """
* Simple BJT Amplifier
VDD vdd 0 DC 5V
Vin vin 0 DC 0.7V

* BJT amplifier (CE configuration)
Q1 vout vin 0 0 NPN_MODEL
Rc vdd vout 1k
Re 0 0 0

.model NPN_MODEL NPN (BF=100 IS=1e-15)

.end
"""

print("="*80)
print("TESTING AMPLIFIER WITH DYNAMIC FITTING (DC + Transient)")
print("="*80)

print("\nRunning pipeline on simple BJT amplifier...")
print("This should:")
print("  1. Run DC sweep on Vin (input voltage)")
print("  2. Run transient simulation for step response")
print("  3. Combine both to create dynamic amplifier model")
print()

result = spice_to_verilog_ams(
    amplifier_netlist,
    output_dir='./output_amp_dynamic_test'
)

print("\n" + "="*80)
print("RESULTS")
print("="*80)

print(f"Pipeline completed!")
print(f"Output directory: ./output_amp_dynamic_test")

# Check for generated files
import os
if os.path.exists('./output_amp_dynamic_test'):
    va_files = [f for f in os.listdir('./output_amp_dynamic_test') if f.endswith('.va')]
    print(f"\nGenerated {len(va_files)} Verilog-AMS files:")
    for va_file in va_files:
        print(f"  - {va_file}")

        # Read and show key parts
        with open(f'./output_amp_dynamic_test/{va_file}', 'r') as f:
            content = f.read()
            # Look for dynamic model indicators
            if 'bandwidth' in content.lower() or 'time_constant' in content.lower():
                print(f"    ✓ Contains dynamic parameters!")
            if 'gain' in content.lower():
                print(f"    ✓ Contains gain parameters!")

print("\n" + "="*80)
