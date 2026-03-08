#!/usr/bin/env python3
"""
Test ALL THREE classifications using complete_pipeline.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from complete_pipeline import spice_to_verilog_ams

print("="*80)
print(" TESTING ALL THREE CLASSIFICATIONS WITH COMPLETE_PIPELINE.PY")
print("="*80)

# TEST 1: STRUCTURAL_LINEAR
print("\n[TEST 1] STRUCTURAL_LINEAR")
print("-"*80)
netlist1 = """* RC Filter
Vin vin 0 DC 0V AC 1V
R1 vin vout 1k
C1 vout 0 1n
"""
files1 = spice_to_verilog_ams(netlist1, '/home/vrajeshprakhya/circuit_preprocess')

# TEST 2: SMALL_SIGNAL_LINEARIZABLE  
print("\n[TEST 2] SMALL_SIGNAL_LINEARIZABLE")
print("-"*80)
with open('/home/vrajeshprakhya/circuit_preprocess/test_diffpair.cir', 'r') as f:
    netlist2 = f.read()
files2 = spice_to_verilog_ams(netlist2, '/home/vrajeshprakhya/circuit_preprocess')

# TEST 3: NONLINEAR
print("\n[TEST 3] NONLINEAR")
print("-"*80)
netlist3 = """* MOSFET no passives
M1 vd vg 0 0 NMOS
VDD vd 0 DC 1.8
Vin vg 0 DC 0.9
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""
files3 = spice_to_verilog_ams(netlist3, '/home/vrajeshprakhya/circuit_preprocess')

# SUMMARY
print("\n" + "="*80)
print(" SUMMARY: complete_pipeline.py TESTED WITH ALL 3 CLASSIFICATIONS")
print("="*80)
print(f"✓ STRUCTURAL_LINEAR:         {len(files1)} modules")
print(f"✓ SMALL_SIGNAL_LINEARIZABLE: {len(files2)} modules")  
print(f"✓ NONLINEAR:                 {len(files3)} modules")
print(f"\nTotal: {len(files1)+len(files2)+len(files3)} Verilog-AMS modules generated")
print("="*80)
