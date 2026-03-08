#!/usr/bin/env python3
"""
Debug independence detection to see why coupling results are backwards
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from independence_detector import test_source_independence
from ngspice_runner import NgspiceRunner

# Test Case 1: Should be INDEPENDENT
# Two separate stages - Vin drives out1, Iin drives out2
independent_netlist = """
Vin in1 0 DC 0 AC 1
M1 out1 in1 0 0 NMOS W=10u L=1u
R1 vdd out1 10k

Iin in2 0 DC 0 AC 1u
R2 in2 0 1k
M2 out2 in2 0 0 NMOS W=10u L=1u
R3 vdd out2 10k

VDD vdd 0 DC 1.8
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

# Test Case 2: Should be COUPLED
# Differential pair - both inp and inn affect outp and outn
coupled_netlist = """
Vinp inp 0 DC 0.9 AC 1
Vinn inn 0 DC 0.9 AC 1

M1 outp inp tail 0 NMOS W=10u L=1u
M2 outn inn tail 0 NMOS W=10u L=1u

Itail tail 0 DC 100u

Rp vdd outp 10k
Rn vdd outn 10k

VDD vdd 0 DC 1.8
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

runner = NgspiceRunner()

print("=" * 80)
print("INDEPENDENCE DETECTION DEBUG")
print("=" * 80)

# Test 1: Independent stages
print("\n[Test 1: Independent Stages]")
print("Expected: INDEPENDENT (two separate stages)")
print("-" * 80)
result1 = test_source_independence(
    independent_netlist, 'in1', 'in2', 'out1', runner, vdd=1.8
)
print(f"Result: {result1['recommendation']}")
print(f"Coupled: {result1['coupled']}")
print(f"Coupling strength: {result1['coupling_strength']:.4f}")
print(f"Test details: {result1['test_details']}")

# Test 2: Differential pair
print("\n[Test 2: Differential Pair]")
print("Expected: COUPLED (both inputs affect differential output)")
print("-" * 80)
result2 = test_source_independence(
    coupled_netlist, 'inp', 'inn', 'outp', runner, vdd=1.8
)
print(f"Result: {result2['recommendation']}")
print(f"Coupled: {result2['coupled']}")
print(f"Coupling strength: {result2['coupling_strength']:.4f}")
print(f"Test details: {result2['test_details']}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Test 1 (Independent): {result1['recommendation']} - {'✓ PASS' if result1['recommendation'] == '1D' else '✗ FAIL'}")
print(f"Test 2 (Coupled): {result2['recommendation']} - {'✓ PASS' if result2['recommendation'] == '2D' else '✗ FAIL'}")
