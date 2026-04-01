#!/usr/bin/env python3
"""Test the DC sweep parser with actual ngspice output"""

from ngspice_runner import NgspiceRunner
from pathlib import Path

# Load the actual ngspice output
output = Path("/tmp/ngspice_dc_test_output.txt").read_text()

print("=== Testing Parser ===\n")
print("Output length:", len(output))
print("\nFirst 500 chars:")
print(output[:500])

# Test the parser
runner = NgspiceRunner()
sweep_var = "v(in)"
observe_vars = ["v(out)"]

print("\n=== Calling _parse_dc_sweep_output ===")
results = runner._parse_dc_sweep_output(output, sweep_var, observe_vars)

print("\n=== Results ===")
for var, values in results.items():
    print(f"{var}: {len(values)} points")
    if len(values) > 0:
        print(f"  First 3: {values[:3]}")
        print(f"  Last 3: {values[-3:]}")
    else:
        print("  NO DATA!")
