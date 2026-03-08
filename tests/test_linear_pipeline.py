#!/usr/bin/env python3
"""
Test the STRUCTURALLY_LINEAR pipeline with an RLC circuit
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from complete_pipeline import spice_to_verilog_ams

# Test with a simple RLC low-pass filter
rlc_netlist = """
* RLC Low-pass filter
Vin vin 0 DC 0V AC 1V
R1 vin vout 1k
C1 vout 0 1n
"""

print("="*70)
print(" TEST: STRUCTURALLY_LINEAR PIPELINE")
print("="*70)
print("\nTest Circuit: RLC Low-Pass Filter")
print(rlc_netlist)

# Run pipeline
saved_files = spice_to_verilog_ams(rlc_netlist, '/home/vrajeshprakhya/circuit_preprocess')

print("\n" + "="*70)
print(" GENERATED FILES")
print("="*70)

for f in saved_files:
    if str(f).endswith('.va'):
        print(f"\n{'='*70}")
        print(f" File: {f.name}")
        print("="*70)
        with open(f, 'r') as file:
            print(file.read())
