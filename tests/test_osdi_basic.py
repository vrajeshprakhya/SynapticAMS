#!/usr/bin/env python3
"""
Minimal test to verify ngspice OSDI/OpenVAF workflow

Tests:
1. Can we find OpenVAF compiler?
2. Can we compile a simple Verilog-A model?
3. Can ngspice load and simulate the .osdi file?
"""

import subprocess
import tempfile
from pathlib import Path

print("="*70)
print(" TESTING NGSPICE OSDI/OpenVAF WORKFLOW")
print("="*70)

# Step 1: Check for OpenVAF
print("\n[1/4] Checking for OpenVAF compiler...")
try:
    result = subprocess.run(['which', 'openvaf'], capture_output=True, text=True)
    if result.returncode == 0:
        openvaf_bin = result.stdout.strip()
        print(f"  ✓ Found: {openvaf_bin}")
    else:
        print("  ✗ Not found in PATH")
        print("\n  To install OpenVAF:")
        print("    Visit: https://openvaf.semimod.de/")
        print("    Or:    https://github.com/pascalkuthe/OpenVAF/releases")
        exit(1)
except Exception as e:
    print(f"  ✗ Error: {e}")
    exit(1)

# Step 2: Create a simple Verilog-A model (voltage-controlled voltage source)
print("\n[2/4] Creating simple Verilog-A model (gain = 2.0)...")

simple_va_code = """
// Simple voltage-controlled voltage source
// out = gain * in

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

# Write to temp file
temp_dir = Path(tempfile.mkdtemp())
va_file = temp_dir / "simple_vcvs.va"
with open(va_file, 'w') as f:
    f.write(simple_va_code)

print(f"  ✓ Created: {va_file}")

# Step 3: Compile with OpenVAF
print("\n[3/4] Compiling with OpenVAF...")
osdi_file = temp_dir / "simple_vcvs.osdi"

try:
    result = subprocess.run(
        [openvaf_bin, str(va_file), '-o', str(osdi_file)],
        capture_output=True,
        text=True,
        timeout=10
    )

    if result.returncode != 0:
        print(f"  ✗ Compilation failed!")
        print(f"  stdout: {result.stdout}")
        print(f"  stderr: {result.stderr}")
        exit(1)

    if not osdi_file.exists():
        print(f"  ✗ OSDI file not created!")
        exit(1)

    print(f"  ✓ Compiled successfully: {osdi_file}")
    print(f"    File size: {osdi_file.stat().st_size} bytes")

except subprocess.TimeoutExpired:
    print("  ✗ Compilation timeout!")
    exit(1)
except Exception as e:
    print(f"  ✗ Error: {e}")
    exit(1)

# Step 4: Test with ngspice
print("\n[4/4] Testing with ngspice...")

# Create a simple netlist that loads the OSDI model
# CORRECT SYNTAX from ngspice examples:
# 1. Define .model referencing Verilog-A module
# 2. Instantiate with N prefix
# 3. Use pre_osdi in .control block
test_netlist = f"""* Test OSDI model loading

* Define model (references Verilog-A module name)
.model vcvs_model simple_vcvs gain=2.0

* Input voltage source
Vin in 0 DC 1.0

* OSDI device instance: N<name> <nodes...> <model_name>
* Number of nodes must match Verilog-A module ports (2 ports = 2 nodes)
Nvcvs out in vcvs_model

.control
pre_osdi {osdi_file}
op
print v(in) v(out)
quit
.endc

.end
"""

# Write netlist to file
netlist_file = temp_dir / "test_osdi.cir"
with open(netlist_file, 'w') as f:
    f.write(test_netlist)

print(f"  Created testbench: {netlist_file}")

# Run ngspice
try:
    result = subprocess.run(
        ['ngspice', '-b', str(netlist_file)],
        capture_output=True,
        text=True,
        timeout=10
    )

    print(f"\n  Return code: {result.returncode}")

    if result.returncode == 0:
        print(f"  ✓ Simulation successful!")

        # Parse output
        output = result.stdout

        # Look for v(in) and v(out)
        import re
        vin_match = re.search(r'v\(in\)\s*=\s*([\d.eE+-]+)', output)
        vout_match = re.search(r'v\(out\)\s*=\s*([\d.eE+-]+)', output)

        if vin_match and vout_match:
            vin = float(vin_match.group(1))
            vout = float(vout_match.group(1))

            print(f"\n  Results:")
            print(f"    V(in)  = {vin:.6f} V")
            print(f"    V(out) = {vout:.6f} V")
            print(f"    Gain   = {vout/vin:.6f} (expected 2.0)")

            if abs(vout/vin - 2.0) < 0.01:
                print(f"\n  ✓ OSDI model working correctly!")
            else:
                print(f"\n  ✗ Unexpected gain value!")
        else:
            print(f"\n  ⚠ Could not parse output:")
            print(output[:500])
    else:
        print(f"  ✗ Simulation failed!")
        print(f"\n  stdout:")
        print(result.stdout[:500])
        print(f"\n  stderr:")
        print(result.stderr[:500])

except subprocess.TimeoutExpired:
    print("  ✗ Simulation timeout!")
except Exception as e:
    print(f"  ✗ Error: {e}")

print("\n" + "="*70)
print(" TEST COMPLETE")
print("="*70)

# Cleanup
print(f"\nTemporary files in: {temp_dir}")
print("(Not deleted for inspection)")
