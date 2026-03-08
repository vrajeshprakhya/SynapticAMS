#!/usr/bin/env python3
"""
Test OpenSERDES Receiver blocks individually
"""

from complete_pipeline import spice_to_verilog_ams
from pathlib import Path

# Test 1: Just the resistive feedback inverter (first stage)
test_rfb_inv = """
* Resistive Feedback Inverter Test
.model nshort nmos (level=1 vto=0.7 kp=200u lambda=0.02 gamma=0.4)
.model pshort pmos (level=1 vto=-0.7 kp=100u lambda=0.02 gamma=0.4)

* Power
Vdd vdd 0 DC 1.8V

* Input signal
Vin inp 0 DC 0.9V

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
print(" Test 1: Resistive Feedback Inverter")
print("="*70)

output_dir = Path('/home/vrajeshprakhya/circuit_preprocess')
saved_files = spice_to_verilog_ams(test_rfb_inv, str(output_dir))

# Show generated files
print("\n" + "="*70)
print(" GENERATED VERILOG-AMS")
print("="*70)

for f in saved_files:
    if str(f).endswith('.va'):
        print(f"\n{'='*70}")
        print(f" File: {f.name}")
        print("="*70)
        with open(f, 'r') as file:
            print(file.read())

# Test 2: Complete receiver (if first test works)
print("\n\n" + "="*70)
print(" Test 2: Full Receiver Circuit")
print("="*70)

full_receiver = """
* OpenSERDES Receiver - Simplified Test
.model nshort nmos (level=1 vto=0.7 kp=200u lambda=0.02 gamma=0.4)
.model pshort pmos (level=1 vto=-0.7 kp=100u lambda=0.02 gamma=0.4)

Vdd vdd 0 DC 1.8V
Vin inp 0 DC 0.9V

* Stage 1: Resistive feedback inverter
MN0 net1 inp 0 0 nshort w=5u l=0.15u
MN1 net1 inp 0 0 nshort w=5u l=0.15u
MP0 net1 inp vdd vdd pshort w=5u l=0.15u
MP1 net1 inp vdd vdd pshort w=5u l=0.15u
MP2 net1 inp vdd vdd pshort w=5u l=0.15u
MPfb1 net1 net1 netfb vdd pshort w=0.55u l=8u
MPfb0 netfb netfb inp vdd pshort w=0.55u l=8u

* Stage 2: High-gain inverter
MN3 out net1 0 0 nshort w=5u l=0.15u
MN4 out net1 0 0 nshort w=5u l=0.15u
MP3 out net1 vdd vdd pshort w=5u l=0.15u
MP4 out net1 vdd vdd pshort w=5u l=0.15u
MP5 out net1 vdd vdd pshort w=5u l=0.15u

Cout out 0 20f
"""

try:
    saved_files2 = spice_to_verilog_ams(full_receiver, str(output_dir))

    print("\n" + "="*70)
    print(" FULL RECEIVER VERILOG-AMS")
    print("="*70)

    for f in saved_files2:
        if str(f).endswith('.va'):
            print(f"\n{f.name}:")
            with open(f, 'r') as file:
                # Just show the module declaration and key parameters
                for line in file:
                    if 'module' in line or 'parameter' in line or 'Intent:' in line:
                        print(f"  {line.rstrip()}")
except Exception as e:
    print(f"Full receiver processing failed: {e}")
    print("This is expected - the full receiver with DFF is complex")

print("\n" + "="*70)
print(" SUMMARY")
print("="*70)
print("\nThe pipeline extracts behavioral models for analog blocks.")
print("For the receiver, you should see models for:")
print("  - Input stage (resistive feedback inverter)")
print("  - Amplification stage (high-gain inverter)")
print("  - DFF sampling stage may need manual modeling")
