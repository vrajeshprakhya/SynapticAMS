#!/usr/bin/env python3
"""
Test small-signal pipeline flow with linear circuit

This tests the complete pipeline with a linear_intent circuit
to verify small-signal model extraction and Verilog-AMS generation.
"""

from complete_pipeline import spice_to_verilog_ams

# Test circuit: Source follower (linear amplifier)
# Signal path: vin → gate → source (through RS) → vout
# This should have linear_intent = True because signal goes through RS (passive)
test_netlist = """
* Source follower (linear buffer)
M1 vdd vin vout 0 NMOS W=10u L=1u
RS vout 0 1k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0.9V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

print("="*70)
print(" TEST: Small-Signal Pipeline")
print("="*70)
print("\nTest Circuit: Source Follower (Linear Buffer)")
print(test_netlist)

# Run pipeline
saved_files = spice_to_verilog_ams(test_netlist, '/tmp')

# Show generated Verilog-AMS
print("\n" + "="*70)
print(" GENERATED VERILOG-AMS CODE")
print("="*70)

for f in saved_files:
    if str(f).endswith('.va'):
        print(f"\n{'='*70}")
        print(f" File: {f.name}")
        print("="*70)
        with open(f, 'r') as file:
            print(file.read())
