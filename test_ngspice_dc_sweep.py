#!/usr/bin/env python3
"""
Minimal test to debug ngspice DC sweep output parsing
"""

import subprocess
import tempfile
from pathlib import Path

# Create a simple test circuit with OSDI model
test_netlist = """* Test DC Sweep with OSDI
V1 in 0 DC 0

.control
pre_osdi my_demo_results/refined/rx_out_n_vs_tx_in_p.osdi
.endc

.model mymodel rx_out_n_vs_tx_in_p
Nmodel in out mymodel

.dc V1 0 1.8 0.3
.print dc v(out)
.end
"""

# Write test netlist
test_file = Path("/tmp/test_dc_sweep.cir")
test_file.write_text(test_netlist)

# Run ngspice and capture output
print("=" * 80)
print("Running ngspice DC sweep test...")
print("=" * 80)

result = subprocess.run(
    ["ngspice", "-b", str(test_file)],
    capture_output=True,
    text=True,
    timeout=10
)

print("\n=== STDOUT ===")
print(result.stdout)

print("\n=== STDERR ===")
print(result.stderr)

print("\n=== Return Code ===")
print(result.returncode)

# Save full output for analysis
Path("/tmp/ngspice_dc_test_output.txt").write_text(result.stdout + "\n\n" + result.stderr)
print("\nFull output saved to: /tmp/ngspice_dc_test_output.txt")
