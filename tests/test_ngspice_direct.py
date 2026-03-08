#!/usr/bin/env python3
"""
Test what ngspice command is actually being generated
"""

from ngspice_runner import NgspiceRunner
import tempfile

test_netlist = """
* Test circuit
.model nshort nmos (level=1 vto=0.7 kp=200u)
.model pshort pmos (level=1 vto=-0.7 kp=100u)

Vdd vdd 0 DC 1.8V
Vin inp 0 DC 0.9V AC 1

MN0 out inp 0 0 nshort w=5u l=0.15u
MP0 out inp vdd vdd pshort w=5u l=0.15u
"""

runner = NgspiceRunner()

# Build the deck that would be sent to ngspice
sweep_params = {
    'sweep_var': 'inp',  # This is a NODE, not a source!
    'start': 0.0,
    'stop': 1.8,
    'step': 0.1,
    'observe': ['out']
}

# Build the deck
deck = runner._build_dc_sweep_deck(test_netlist, sweep_params, {})

print("="*70)
print(" NGSPICE DECK (INCORRECT - sweeping node instead of source)")
print("="*70)
print(deck)

print("\n" + "="*70)
print(" WHAT IT SHOULD BE (sweeping source Vin)")
print("="*70)

# Correct version
correct_deck = test_netlist + """
.dc Vin 0.0 1.8 0.1

.control
run
print inp out
quit
.endc

.end
"""
print(correct_deck)

print("\n" + "="*70)
print(" TESTING CORRECT VERSION")
print("="*70)

# Write correct version to file and test
with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
    f.write(correct_deck)
    deck_file = f.name

import subprocess
result = subprocess.run(
    ['ngspice', '-b', deck_file],
    capture_output=True,
    text=True
)

print(f"Return code: {result.returncode}")
if result.returncode == 0:
    print("✓ Success!")
    print("\nOutput (first 50 lines):")
    for line in result.stdout.split('\n')[:50]:
        print(line)
else:
    print("✗ Failed")
    print("\nStderr:")
    print(result.stderr)

import os
os.unlink(deck_file)
