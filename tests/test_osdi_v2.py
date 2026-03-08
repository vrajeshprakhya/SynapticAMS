#!/usr/bin/env python3
"""
Test OSDI with proper loading sequence

According to ngspice manual, OSDI models need to be loaded
before the circuit is parsed. Try different approaches.
"""

import subprocess
import tempfile
from pathlib import Path

print("="*70)
print(" TESTING OSDI LOADING METHODS")
print("="*70)

# Compile the model first
print("\n[1/3] Compiling Verilog-A model...")

simple_va = """
`include "disciplines.vams"
module simple_vcvs(out, in);
    input in;
    output out;
    electrical in, out;
    parameter real gain = 2.0;
    analog begin
        V(out) <+ gain * V(in);
    end
endmodule
"""

temp_dir = Path(tempfile.mkdtemp())
va_file = temp_dir / "simple_vcvs.va"
osdi_file = temp_dir / "simple_vcvs.osdi"

with open(va_file, 'w') as f:
    f.write(simple_va)

result = subprocess.run(
    ['openvaf', str(va_file), '-o', str(osdi_file)],
    capture_output=True, timeout=10
)

if result.returncode != 0 or not osdi_file.exists():
    print(f"  ✗ Compilation failed")
    exit(1)

print(f"  ✓ Compiled: {osdi_file}")

# Method 1: Try pre_osdi command
print("\n[2/3] Method 1: Using pre_osdi command...")

netlist1 = f"""* Test with pre_osdi

.pre_osdi {osdi_file}

Vin in 0 DC 1.0
Nvcvs out in 0 simple_vcvs

.control
op
print v(in) v(out)
quit
.endc

.end
"""

test_file1 = temp_dir / "test_pre_osdi.cir"
with open(test_file1, 'w') as f:
    f.write(netlist1)

result1 = subprocess.run(
    ['ngspice', '-b', str(test_file1)],
    capture_output=True, text=True, timeout=10
)

if result1.returncode == 0 and 'v(out)' in result1.stdout:
    print("  ✓ pre_osdi works!")
    print(f"  Output: {result1.stdout[result1.stdout.find('v(in)'):result1.stdout.find('v(in)')+100]}")
else:
    print("  ✗ pre_osdi failed")
    if 'pre_osdi' in result1.stderr and 'unimplemented' in result1.stderr:
        print("    (pre_osdi command not recognized)")

# Method 2: Load in init file
print("\n[3/3] Method 2: Using .spiceinit file...")

init_file = temp_dir / ".spiceinit"
with open(init_file, 'w') as f:
    f.write(f"osdi {osdi_file}\n")

netlist2 = """* Test with .spiceinit

Vin in 0 DC 1.0
Nvcvs out in 0 simple_vcvs

.control
op
print v(in) v(out)
quit
.endc

.end
"""

test_file2 = temp_dir / "test_init.cir"
with open(test_file2, 'w') as f:
    f.write(netlist2)

# Run from temp_dir so .spiceinit is found
result2 = subprocess.run(
    ['ngspice', '-b', 'test_init.cir'],
    capture_output=True, text=True, timeout=10,
    cwd=str(temp_dir)
)

if result2.returncode == 0 and 'v(out)' in result2.stdout:
    print("  ✓ .spiceinit works!")

    # Parse output
    import re
    vin_match = re.search(r'v\(in\)\s*=\s*([\d.eE+-]+)', result2.stdout)
    vout_match = re.search(r'v\(out\)\s*=\s*([\d.eE+-]+)', result2.stdout)

    if vin_match and vout_match:
        vin = float(vin_match.group(1))
        vout = float(vout_match.group(1))
        print(f"    V(in)  = {vin:.6f} V")
        print(f"    V(out) = {vout:.6f} V")
        print(f"    Gain   = {vout/vin:.6f} (expected 2.0)")
else:
    print("  ✗ .spiceinit failed")
    print(f"  stderr: {result2.stderr[:200]}")

print("\n" + "="*70)
print(" RESULTS")
print("="*70)
print(f"\nTest files in: {temp_dir}")
print("\nIf both methods failed, check ngspice manual chapter 13:")
print("  https://ngspice.sourceforge.io/docs/ngspice-manual.pdf")
