#!/usr/bin/env python3
"""
Test the complete pipeline with integrated equivalence checking
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from complete_pipeline import spice_to_verilog_ams

# Test 1: RC filter (STRUCTURAL_LINEAR)
print("="*70)
print(" TEST: Complete Pipeline with Equivalence Checking")
print("="*70)

rc_netlist = """* RC Filter
Vin vin 0 DC 0V AC 1V
R1 vin vout 1k
C1 vout 0 1n
"""

print("\nCircuit: RC Lowpass Filter (STRUCTURAL_LINEAR)")
print("-"*70)

saved_files = spice_to_verilog_ams(rc_netlist, '/home/vrajeshprakhya/circuit_preprocess')

print("\n" + "="*70)
print(f" Completed! Generated {len(saved_files)} files")
print("="*70)
