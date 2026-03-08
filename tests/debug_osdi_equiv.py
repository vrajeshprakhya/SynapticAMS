#!/usr/bin/env python3
"""
Debug OSDI equivalence checking for receiver models
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from equivalence_checker_osdi import OSDIEquivalenceChecker
from pathlib import Path

# Read the generated Verilog-AMS file
va_file = Path('/home/vrajeshprakhya/circuit_preprocess/out_vs_inp.va')
with open(va_file) as f:
    verilog_code = f.read()

print("="*70)
print(" DEBUGGING OSDI EQUIVALENCE CHECK")
print("="*70)

# Original test netlist (simplified)
test_netlist = """
* Resistive Feedback Inverter Test
.model nshort nmos (level=1 vto=0.7 kp=200u)
.model pshort pmos (level=1 vto=-0.7 kp=100u)

Vdd vdd 0 DC 1.8V
Vin inp 0 DC 0.9V AC 1

MN0 out inp 0 0 nshort w=5u l=0.15u
MN1 out inp 0 0 nshort w=5u l=0.15u
MP0 out inp vdd vdd pshort w=5u l=0.15u
MP1 out inp vdd vdd pshort w=5u l=0.15u
MPfb1 out out net06 vdd pshort w=0.55u l=8u
MPfb0 net06 net06 inp vdd pshort w=0.55u l=8u

Cout out 0 10f
"""

print("\n[1/4] Creating equivalence checker...")
checker = OSDIEquivalenceChecker(abs_tol=0.01, rel_tol=0.05)

print("\n[2/4] Testing OSDI compilation...")
try:
    osdi_file = checker._compile_to_osdi(verilog_code, 'out_vs_inp')
    print(f"  ✓ Compiled to: {osdi_file}")
except Exception as e:
    print(f"  ✗ Compilation failed: {e}")
    exit(1)

print("\n[3/4] Testing SPICE reference simulation...")
import numpy as np
test_vectors = np.array([[0.5], [0.9], [1.2]])  # 3 test points

try:
    spice_results = checker._simulate_spice(
        test_netlist, ['inp'], ['out'], test_vectors
    )
    print(f"  ✓ SPICE simulation successful")
    print(f"    out values: {spice_results['out']}")
except Exception as e:
    print(f"  ✗ SPICE simulation failed: {e}")
    import traceback
    traceback.print_exc()

print("\n[4/4] Testing OSDI simulation...")
try:
    osdi_results = checker._simulate_osdi(
        osdi_file, 'out_vs_inp', ['inp'], ['out'], test_vectors
    )
    print(f"  ✓ OSDI simulation successful")
    print(f"    out values: {osdi_results['out']}")
except Exception as e:
    print(f"  ✗ OSDI simulation failed: {e}")
    import traceback
    traceback.print_exc()

print("\n[5/4] Testing full equivalence check...")
try:
    result = checker.check_equivalence(
        test_netlist, verilog_code, 'out_vs_inp',
        input_names=['inp'], output_names=['out'], n_test_points=5
    )
    print(f"  Result: {result}")
except Exception as e:
    print(f"  ✗ Full check failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
print("If SPICE works but OSDI fails, check the OSDI testbench netlist")
print("If both fail, check voltage source modification logic")
