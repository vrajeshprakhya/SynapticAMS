#!/usr/bin/env python3
"""
Test OpenSERDES Receiver - with proper signal sources
"""

from complete_pipeline import spice_to_verilog_ams
from pathlib import Path

# Test: Resistive feedback inverter with AC signal source
test_rfb_inv = """
* Resistive Feedback Inverter Test
.model nshort nmos (level=1 vto=0.7 kp=200u lambda=0.02 gamma=0.4)
.model pshort pmos (level=1 vto=-0.7 kp=100u lambda=0.02 gamma=0.4)

* Power
Vdd vdd 0 DC 1.8V

* Input signal - AC 1 makes it a signal source!
Vin inp 0 DC 0.9V AC 1

* Resistive feedback inverter
* Inverter core
MN0 out inp 0 0 nshort w=5u l=0.15u
MN1 out inp 0 0 nshort w=5u l=0.15u
MN2 out inp 0 0 nshort w=5u l=0.15u
MP0 out inp vdd vdd pshort w=5u l=0.15u
MP1 out inp vdd vdd pshort w=5u l=0.15u
MP2 out inp vdd vdd pshort w=5u l=0.15u
MP3 out inp vdd vdd pshort w=5u l=0.15u
MP4 out inp vdd vdd pshort w=5u l=0.15u
MP5 out inp vdd vdd pshort w=5u l=0.15u

* Resistive feedback (long-channel PMOS)
MPfb1 out out net06 vdd pshort w=0.55u l=8u
MPfb0 net06 net06 inp vdd pshort w=0.55u l=8u

* Load
Cout out 0 10f
"""

print("="*70)
print(" OpenSERDES Resistive Feedback Inverter → Verilog-AMS")
print("="*70)

output_dir = Path('/home/vrajeshprakhya/circuit_preprocess')
saved_files = spice_to_verilog_ams(test_rfb_inv, str(output_dir))

# Show generated files
print("\n" + "="*70)
print(" GENERATED VERILOG-AMS MODULES")
print("="*70)

for f in saved_files:
    if str(f).endswith('.va'):
        print(f"\n{'='*70}")
        print(f" File: {f.name}")
        print("="*70)
        with open(f, 'r') as file:
            print(file.read())

if not saved_files:
    print("\n⚠ No Verilog-AMS files generated")
    print("\nThis might happen if the circuit is too complex or")
    print("simulation_axes couldn't be determined.")
    print("\nChecking if simulations ran...")
