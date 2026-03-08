#!/usr/bin/env python3
"""
Test 2D sweep in isolation to debug parsing issues
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from ngspice_runner import NgspiceRunner

# Simple test circuit
netlist = """
Vinp inp 0 DC 0
Vinn inn 0 DC 0

M1 outp inp tail 0 NMOS W=10u L=1u
M2 outn inn tail 0 NMOS W=10u L=1u

Itail tail 0 DC 100u

Rp vdd outp 10k
Rn vdd outn 10k

VDD vdd 0 DC 1.8

.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

runner = NgspiceRunner()

# Try 2D sweep
sweep_params = {
    'sweep_var_1': 'inp',
    'start_1': 0.0,
    'stop_1': 1.8,
    'step_1': 0.6,  # 3 points
    'sweep_var_2': 'inn',
    'start_2': 0.0,
    'stop_2': 1.8,
    'step_2': 0.6,  # 3 points
    'observe': ['outp', 'outn']
}

print("Testing 2D DC sweep...")
print(f"Sweep: {sweep_params['sweep_var_1']} [{sweep_params['start_1']} → {sweep_params['stop_1']}]")
print(f"       {sweep_params['sweep_var_2']} [{sweep_params['start_2']} → {sweep_params['stop_2']}]")
print()

try:
    results = runner.dc_sweep_2d(netlist, sweep_params)
    print("✓ SUCCESS!")
    print(f"Results keys: {list(results.keys())}")
    for key, val in results.items():
        print(f"  {key}: shape={val.shape if hasattr(val, 'shape') else len(val)}")
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
