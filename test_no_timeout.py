#!/usr/bin/env python3
"""
Quick test to verify no-timeout ngspice works
"""
from ngspice_runner import NgspiceRunner
import time

# Simple inverter netlist
netlist = """
* Simple NMOS inverter
VDD dd 0 DC 1.8
Vin in 0 DC 0

M1 out in 0 0 NMOS W=1u L=0.18u
M2 out in dd dd PMOS W=2u L=0.18u

.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=200u)
.model PMOS PMOS (LEVEL=1 VTO=-0.4 KP=100u)
"""

runner = NgspiceRunner()
print(f"NgspiceRunner timeout: {runner.timeout}")
print(f"Running DC sweep with NO timeout...")

start = time.time()
result = runner.dc_sweep(netlist, {
    'sweep_var': 'Vin',
    'start': 0.0,
    'stop': 1.8,
    'step': 0.1,
    'observe': ['Vin', 'v(out)']
})
elapsed = time.time() - start

print(f"✓ Simulation completed in {elapsed:.2f}s")
print(f"  Points: {len(result['Vin'])}")
print(f"  Vin range: [{result['Vin'][0]:.2f}, {result['Vin'][-1]:.2f}]")
print(f"  Vout range: [{result['v(out)'][0]:.2f}, {result['v(out)'][-1]:.2f}]")
