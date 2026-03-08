#!/usr/bin/env python3
"""
Test what ngspice actually returns
"""

from ngspice_runner import NgspiceRunner

netlist = """
* Common source amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

sweep_params = {
    'sweep_var': 'vin',
    'start': 0.0,
    'stop': 1.8,
    'step': 0.05,
    'observe': ['vout']
}

runner = NgspiceRunner()

print("Running ngspice DC sweep...")
results = runner.dc_sweep(netlist, sweep_params)

print("\nResults dictionary keys:", results.keys())

for key, values in results.items():
    print(f"\n{key}:")
    print(f"  Type: {type(values)}")
    print(f"  Shape: {values.shape if hasattr(values, 'shape') else 'N/A'}")
    print(f"  Length: {len(values) if hasattr(values, '__len__') else 'N/A'}")
    print(f"  First 5 values: {values[:5] if hasattr(values, '__getitem__') else 'N/A'}")

# Now test fit
from fit_transfer_function_dc_sweep import fit_transfer_function

x = results['vin']
y = results['vout']

print(f"\nTesting fit with x.shape={x.shape}, y.shape={y.shape}")

try:
    model = fit_transfer_function(x, y)
    print("Fit SUCCESS!")
    print(f"Intent: {model['intent']}")
    print(f"Model type: {model['model_type']}")
except Exception as e:
    print(f"Fit FAILED: {e}")
    import traceback
    traceback.print_exc()
