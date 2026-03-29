#!/usr/bin/env python3
"""
Test dynamic fitting on VCO block only
"""
from pipeline_ext.complete_pipeline import spice_to_verilog_ams

# Simple VCO netlist
vco_netlist = """
* Ring Oscillator VCO Test
.include subcircuits/vco_sub.cir

VDD dd 0 DC 3.3
Vcont vcont 0 DC 1.5

* VCO instance: ro_vco(aout, dout, cont, vdd)
Xvco clk_out digital_out vcont dd ro_vco

* Load capacitor
Cload clk_out 0 0.5pF

.control
.endc
.end
"""

print("="*80)
print("TESTING VCO WITH DYNAMIC FITTING (DC + Transient)")
print("="*80)

print("\nRunning programmatic pipeline on VCO...")
print("This should:")
print("  1. Run DC sweep on Vcont (control voltage)")
print("  2. Run transient simulation for oscillation")
print("  3. Combine both to create dynamic model")
print()

result = spice_to_verilog_ams(
    vco_netlist,
    output_dir='./output_vco_dynamic_test'
)

print("\n" + "="*80)
print("RESULTS")
print("="*80)

print(f"Pipeline completed!")
print(f"Output directory: ./output_vco_dynamic_test")

# Check for generated files
import os
if os.path.exists('./output_vco_dynamic_test'):
    va_files = [f for f in os.listdir('./output_vco_dynamic_test') if f.endswith('.va')]
    print(f"\nGenerated {len(va_files)} Verilog-AMS files:")
    for va_file in va_files:
        print(f"  - {va_file}")

print("\n" + "="*80)
