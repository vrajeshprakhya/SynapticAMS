#!/usr/bin/env python3
"""
Test OSDI with ngspice interactive mode

Use a command script that:
1. Loads OSDI library
2. Then sources the netlist
"""

import subprocess
import tempfile
from pathlib import Path

print("="*70)
print(" TESTING OSDI WITH INTERACTIVE MODE")
print("="*70)

# Compile the model
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

# Create netlist WITHOUT the device instantiation yet
print("\n[2/3] Creating netlist and command script...")

# Just the voltage source, no device yet
partial_netlist = """* Partial netlist - no OSDI device yet

Vin in 0 DC 1.0

.end
"""

netlist_file = temp_dir / "circuit.cir"
with open(netlist_file, 'w') as f:
    f.write(partial_netlist)

# Create a command script for ngspice
# This will be executed in order
command_script = f"""* Ngspice command script
* Load OSDI first, then add device, then simulate

* Load OSDI library
osdi {osdi_file}

* Load base circuit
source {netlist_file}

* Now add the OSDI device using alter/create commands
* Actually, we need circbyline to add components
circbyline Nvcvs out in 0 simple_vcvs

* Run simulation
op
print v(in) v(out)

quit
"""

script_file = temp_dir / "commands.txt"
with open(script_file, 'w') as f:
    f.write(command_script)

print(f"  ✓ Created script: {script_file}")

# Method 1: Run script with -o (batch mode with script)
print("\n[3/3] Running ngspice with command script...")

result = subprocess.run(
    ['ngspice', '-b', '-o', str(temp_dir / 'output.log'), str(script_file)],
    capture_output=True, text=True, timeout=10
)

print(f"  Return code: {result.returncode}")

if result.returncode == 0:
    print("  ✓ Executed successfully!")

    # Check output
    output_log = temp_dir / 'output.log'
    if output_log.exists():
        with open(output_log) as f:
            content = f.read()
            print("\n  Output log content:")
            print(content[-500:] if len(content) > 500 else content)
else:
    print("  ✗ Execution failed")
    print(f"\n  stdout:\n{result.stdout[:300]}")
    print(f"\n  stderr:\n{result.stderr[:300]}")

# Alternative: Try with stdin
print("\n[Alternative] Trying with stdin piping...")

# Send commands via stdin
commands_stdin = f"""osdi {osdi_file}
source {netlist_file}
listing
quit
"""

result2 = subprocess.run(
    ['ngspice', '-p'],  # -p = pipe mode
    input=commands_stdin,
    capture_output=True,
    text=True,
    timeout=10
)

if 'simple_vcvs' in result2.stdout:
    print("  ✓ OSDI model loaded successfully!")
    print("  Model appears in listing")
else:
    print("  ⚠ Check if model loaded:")
    print(result2.stdout[-500:] if len(result2.stdout) > 500 else result2.stdout)

print("\n" + "="*70)
print(f"Test files in: {temp_dir}")
print("\nNote: circbyline might not work for OSDI devices.")
print("May need to create complete netlist after loading OSDI.")
