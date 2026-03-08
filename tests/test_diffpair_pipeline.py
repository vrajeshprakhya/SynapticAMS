#!/usr/bin/env python3
"""
Test the complete pipeline with a realistic differential pair circuit
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from complete_pipeline import spice_to_verilog_ams

# Read the differential pair netlist
with open('/home/vrajeshprakhya/circuit_preprocess/test_diffpair.cir', 'r') as f:
    test_netlist_diffpair = f.read()

print("=" * 80)
print("TEST: BJT Differential Pair (Realistic Circuit)")
print("=" * 80)
print("\nCircuit Description:")
print("- Q1, Q2: Differential pair (NPN BJTs)")
print("- Q3, Q4: Current mirror bias")
print("- RC1, RC2: Collector loads (10k)")
print("- RS1, RS2: Source resistors (1k)")
print("- VCC = +12V, VEE = -12V")
print("=" * 80)

saved_files = spice_to_verilog_ams(test_netlist_diffpair, '/home/vrajeshprakhya/circuit_preprocess')

print("\n\n" + "=" * 80)
print("GENERATED VERILOG-AMS CODE")
print("=" * 80)

for f in saved_files:
    print(f"\n{'='*80}")
    print(f"File: {f.name}")
    print('='*80)
    with open(f, 'r') as file:
        print(file.read())
