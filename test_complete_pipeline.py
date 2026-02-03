#!/usr/bin/env python3
"""
Test the complete pipeline with a properly biased circuit
"""

from complete_pipeline import spice_to_verilog_ams

# Test 1: Common-source amplifier with proper bias
test_netlist_cs = """
* Common source amplifier (properly biased)
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0.9V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

print("=" * 80)
print("TEST 1: Common-Source Amplifier (Linearizable)")
print("=" * 80)

saved_files = spice_to_verilog_ams(test_netlist_cs, '/home/vrajeshprakhya/circuit_preprocess')

print("\n\nGenerated Verilog-AMS:")
for f in saved_files:
    print(f"\n{'='*80}")
    print(f"File: {f.name}")
    print('='*80)
    with open(f, 'r') as file:
        print(file.read())

print("\n\n")

# Test 2: Nonlinear circuit (needs DC sweep, not small-signal)
test_netlist_nonlinear = """
* Simple diode-connected MOSFET (nonlinear)
M1 vd vd 0 0 NMOS W=10u L=1u
Vin vd 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

print("=" * 80)
print("TEST 2: Diode-Connected MOSFET (Nonlinear)")
print("=" * 80)

saved_files = spice_to_verilog_ams(test_netlist_nonlinear, '/home/vrajeshprakhya/circuit_preprocess')

print("\n\nGenerated Verilog-AMS:")
for f in saved_files:
    print(f"\n{'='*80}")
    print(f"File: {f.name}")
    print('='*80)
    with open(f, 'r') as file:
        print(file.read())
