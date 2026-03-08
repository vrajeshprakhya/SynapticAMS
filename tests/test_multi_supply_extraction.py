#!/usr/bin/env python3
"""
Test multi-supply voltage extraction from SPICE netlists

Tests various scenarios:
- Single supply (1.8V)
- Dual supply (3.3V + 1.8V analog/digital)
- Bipolar supply (+5V, -5V)
- Multi-domain (3.3V I/O, 1.8V core, 1.0V ultra-low-power)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from equivalence_checker import EquivalenceChecker

def test_single_supply():
    """Test single 1.8V supply extraction"""
    netlist = """
* Single supply circuit
VDD vdd 0 DC 1.8
Vin in 0 DC 0
M1 out in 0 0 NMOS W=10u L=1u
RD vdd out 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    supplies = checker._extract_all_supplies_from_netlist(netlist)
    vdd = checker._extract_vdd_from_netlist(netlist)

    print("=" * 70)
    print("Test 1: Single Supply (1.8V)")
    print("=" * 70)
    print(f"All supplies: {supplies}")
    print(f"VDD (max): {vdd}V")
    print(f"Expected: {{'vdd': 1.8}}, max = 1.8V")
    print(f"✓ PASS" if vdd == 1.8 and supplies == {'vdd': 1.8} else "✗ FAIL")
    print()

    return vdd == 1.8 and supplies == {'vdd': 1.8}


def test_dual_supply_analog_digital():
    """Test dual supply: 3.3V analog + 1.8V digital"""
    netlist = """
* Dual supply: analog and digital domains
VDDA vdda 0 DC 3.3
VDDD vddd 0 DC 1.8
Vin in 0 DC 0
M1 out_analog in 0 0 NMOS W=20u L=0.5u
M2 out_digital in 0 0 NMOS W=10u L=1u
RD1 vdda out_analog 10k
RD2 vddd out_digital 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    supplies = checker._extract_all_supplies_from_netlist(netlist)
    vdd = checker._extract_vdd_from_netlist(netlist)

    print("=" * 70)
    print("Test 2: Dual Supply (3.3V Analog + 1.8V Digital)")
    print("=" * 70)
    print(f"All supplies: {supplies}")
    print(f"VDD (max): {vdd}V")
    print(f"Expected: {{'vdda': 3.3, 'vddd': 1.8}}, max = 3.3V")

    expected_supplies = {'vdda': 3.3, 'vddd': 1.8}
    supplies_match = supplies == expected_supplies
    vdd_match = vdd == 3.3

    print(f"✓ PASS" if supplies_match and vdd_match else "✗ FAIL")
    print()

    return supplies_match and vdd_match


def test_bipolar_supply():
    """Test bipolar supply: +5V and -5V"""
    netlist = """
* Bipolar supply
VDD vdd 0 DC 5.0
VSS vss 0 DC -5.0
Vin in 0 DC 0
M1 out in vss 0 NMOS W=10u L=1u
RD vdd out 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    supplies = checker._extract_all_supplies_from_netlist(netlist)
    vdd = checker._extract_vdd_from_netlist(netlist)

    print("=" * 70)
    print("Test 3: Bipolar Supply (+5V / -5V)")
    print("=" * 70)
    print(f"All supplies: {supplies}")
    print(f"VDD (max): {vdd}V")
    print(f"Expected: {{'vdd': 5.0, 'vss': -5.0}}, max = 5.0V")

    expected_supplies = {'vdd': 5.0, 'vss': -5.0}
    supplies_match = supplies == expected_supplies
    vdd_match = vdd == 5.0

    print(f"✓ PASS" if supplies_match and vdd_match else "✗ FAIL")
    print()

    return supplies_match and vdd_match


def test_multi_domain():
    """Test multi-domain: 3.3V I/O, 1.8V core, 1.0V low-power"""
    netlist = """
* Multi-domain supply
VDDIO vddio 0 DC 3.3
VDDCORE vddcore 0 DC 1.8
VDDLP vddlp 0 DC 1.0
Vin in 0 DC 0
M1 out_io in 0 0 NMOS W=30u L=0.35u
M2 out_core in 0 0 NMOS W=20u L=0.5u
M3 out_lp in 0 0 NMOS W=10u L=1u
RD1 vddio out_io 10k
RD2 vddcore out_core 10k
RD3 vddlp out_lp 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    supplies = checker._extract_all_supplies_from_netlist(netlist)
    vdd = checker._extract_vdd_from_netlist(netlist)

    print("=" * 70)
    print("Test 4: Multi-Domain (3.3V I/O + 1.8V Core + 1.0V LP)")
    print("=" * 70)
    print(f"All supplies: {supplies}")
    print(f"VDD (max): {vdd}V")
    print(f"Expected: {{'vddio': 3.3, 'vddcore': 1.8, 'vddlp': 1.0}}, max = 3.3V")

    expected_supplies = {'vddio': 3.3, 'vddcore': 1.8, 'vddlp': 1.0}
    supplies_match = supplies == expected_supplies
    vdd_match = vdd == 3.3

    print(f"✓ PASS" if supplies_match and vdd_match else "✗ FAIL")
    print()

    return supplies_match and vdd_match


def test_no_supply():
    """Test netlist with no explicit supply (should default to 1.8V)"""
    netlist = """
* Circuit with no VDD (maybe using .param or subcircuit)
Vin in 0 DC 0
M1 out in 0 0 NMOS W=10u L=1u
R1 2 out 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    supplies = checker._extract_all_supplies_from_netlist(netlist)
    vdd = checker._extract_vdd_from_netlist(netlist)

    print("=" * 70)
    print("Test 5: No Explicit Supply (Default)")
    print("=" * 70)
    print(f"All supplies: {supplies}")
    print(f"VDD (max): {vdd}V")
    print(f"Expected: {{}}, max = 1.8V (default)")

    supplies_match = supplies == {}
    vdd_match = vdd == 1.8  # Default

    print(f"✓ PASS" if supplies_match and vdd_match else "✗ FAIL")
    print()

    return supplies_match and vdd_match


def test_with_small_signals():
    """Test that small signal sources (<0.5V) are filtered out"""
    netlist = """
* Circuit with power supply and small signal sources
VDD vdd 0 DC 3.3
Vin in 0 DC 0
Vac ac_sig 0 DC 0 AC 0.1
M1 out in 0 0 NMOS W=10u L=1u
RD vdd out 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    supplies = checker._extract_all_supplies_from_netlist(netlist)
    vdd = checker._extract_vdd_from_netlist(netlist)

    print("=" * 70)
    print("Test 6: Filter Small Signals (<0.5V)")
    print("=" * 70)
    print(f"All supplies: {supplies}")
    print(f"VDD (max): {vdd}V")
    print(f"Expected: {{'vdd': 3.3}} (Vac filtered out), max = 3.3V")

    # Should only contain VDD, not the AC signal source
    supplies_match = supplies == {'vdd': 3.3}
    vdd_match = vdd == 3.3

    print(f"✓ PASS" if supplies_match and vdd_match else "✗ FAIL")
    print()

    return supplies_match and vdd_match


if __name__ == "__main__":
    print("\n")
    print("█" * 70)
    print("  MULTI-SUPPLY VOLTAGE EXTRACTION TESTS")
    print("█" * 70)
    print("\n")

    results = []

    results.append(("Single Supply (1.8V)", test_single_supply()))
    results.append(("Dual Supply (3.3V + 1.8V)", test_dual_supply_analog_digital()))
    results.append(("Bipolar Supply (+5V / -5V)", test_bipolar_supply()))
    results.append(("Multi-Domain (3 supplies)", test_multi_domain()))
    results.append(("No Supply (Default)", test_no_supply()))
    results.append(("Filter Small Signals", test_with_small_signals()))

    print("\n")
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status:8} - {test_name}")

    total = len(results)
    passed = sum(1 for _, p in results if p)

    print("=" * 70)
    print(f"Total: {passed}/{total} tests passed")
    print("=" * 70)

    if passed == total:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        sys.exit(1)
