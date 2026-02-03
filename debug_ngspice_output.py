#!/usr/bin/env python3
"""
Capture raw ngspice output to see what we're parsing
"""

import subprocess
import tempfile
from pathlib import Path

netlist = """
* Common source amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)

.dc Vin 0 1.8 0.36

.control
run
print vin vout
quit
.endc

.end
"""

# Write and execute
with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
    f.write(netlist)
    cir_file = f.name

result = subprocess.run(
    ['ngspice', '-b', cir_file],
    capture_output=True,
    text=True
)

Path(cir_file).unlink()

print("=" * 60)
print("NGSPICE RAW OUTPUT:")
print("=" * 60)
print(result.stdout)
print("\n" + "=" * 60)
print("STDERR:")
print("=" * 60)
print(result.stderr)
