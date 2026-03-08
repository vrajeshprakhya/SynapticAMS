#!/usr/bin/env python3
"""
Test multi-current source extraction from SPICE netlists

Tests various scenarios:
- Single current source (100µA)
- Multiple current sources (100µA, 10µA, 1mA)
- Different units (A, mA, µA, nA)
- No current sources (default)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from equivalence_checker import EquivalenceChecker

def test_single_current():
    """Test single 100µA current source extraction"""
    netlist = """
* Single current source
VDD vdd 0 DC 1.8
Ibias bias 0 DC 100uA
M1 out bias 0 0 NMOS W=10u L=1u
RD vdd out 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    currents = checker._extract_all_currents_from_netlist(netlist)
    max_current = checker._extract_max_current_from_netlist(netlist)

    print("=" * 70)
    print("Test 1: Single Current Source (100µA)")
    print("=" * 70)
    print(f"All currents: {currents}")
    print(f"Max current: {max_current*1e6:.1f}µA")
    print(f"Expected: {{'bias': 100e-6}}, max = 100µA")

    expected_currents = {'bias': 100e-6}
    currents_match = all(
        abs(currents.get(k, 0) - v) < 1e-12 for k, v in expected_currents.items()
    ) and len(currents) == len(expected_currents)
    max_match = abs(max_current - 100e-6) < 1e-9

    print(f"✓ PASS" if currents_match and max_match else "✗ FAIL")
    print()

    return currents_match and max_match


def test_multiple_currents():
    """Test multiple current sources with different magnitudes"""
    netlist = """
* Multiple current sources
VDD vdd 0 DC 1.8
Ibias1 bias1 0 DC 100uA
Ibias2 bias2 0 DC 10uA
Iref ref 0 DC 1mA
M1 out1 bias1 0 0 NMOS W=20u L=1u
M2 out2 bias2 0 0 NMOS W=10u L=1u
M3 out3 ref 0 0 NMOS W=50u L=0.5u
RD1 vdd out1 10k
RD2 vdd out2 10k
RD3 vdd out3 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    currents = checker._extract_all_currents_from_netlist(netlist)
    max_current = checker._extract_max_current_from_netlist(netlist)

    print("=" * 70)
    print("Test 2: Multiple Current Sources (100µA, 10µA, 1mA)")
    print("=" * 70)
    print(f"All currents: {currents}")
    print(f"Max current: {max_current*1e6:.1f}µA")
    print(f"Expected: {{'bias1': 100e-6, 'bias2': 10e-6, 'ref': 1e-3}}, max = 1000µA")

    expected_currents = {'bias1': 100e-6, 'bias2': 10e-6, 'ref': 1e-3}
    currents_match = all(
        abs(currents.get(k, 0) - v) < 1e-12 for k, v in expected_currents.items()
    ) and len(currents) == len(expected_currents)
    max_match = abs(max_current - 1e-3) < 1e-9

    print(f"✓ PASS" if currents_match and max_match else "✗ FAIL")
    print()

    return currents_match and max_match


def test_various_units():
    """Test current sources with various units"""
    netlist = """
* Current sources with different units
VDD vdd 0 DC 3.3
I1 n1 0 DC 1mA
I2 n2 0 DC 500uA
I3 n3 0 DC 100nA
I4 n4 0 DC 0.001A
M1 out n1 0 0 NMOS W=10u L=1u
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    currents = checker._extract_all_currents_from_netlist(netlist)
    max_current = checker._extract_max_current_from_netlist(netlist)

    print("=" * 70)
    print("Test 3: Various Current Units (mA, µA, nA, A)")
    print("=" * 70)
    print(f"All currents: {currents}")
    print(f"Max current: {max_current*1e3:.3f}mA")

    # All should be normalized to Amps
    # I1: 1mA = 1e-3 A
    # I2: 500µA = 500e-6 A
    # I3: 100nA = 100e-9 A
    # I4: 0.001A = 1e-3 A
    expected_currents = {'n1': 1e-3, 'n2': 500e-6, 'n3': 100e-9, 'n4': 1e-3}

    print(f"Expected: {expected_currents}, max = 1mA")

    # Check if all values match (with tolerance for floating point)
    currents_match = all(
        abs(currents.get(k, 0) - v) < 1e-12 for k, v in expected_currents.items()
    ) and len(currents) == len(expected_currents)

    max_match = abs(max_current - 1e-3) < 1e-9

    print(f"✓ PASS" if currents_match and max_match else "✗ FAIL")
    print()

    return currents_match and max_match


def test_no_current_sources():
    """Test netlist with no current sources (should default to 100µA)"""
    netlist = """
* Circuit with no current sources
VDD vdd 0 DC 1.8
Vin in 0 DC 0
M1 out in 0 0 NMOS W=10u L=1u
RD vdd out 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    currents = checker._extract_all_currents_from_netlist(netlist)
    max_current = checker._extract_max_current_from_netlist(netlist)

    print("=" * 70)
    print("Test 4: No Current Sources (Default)")
    print("=" * 70)
    print(f"All currents: {currents}")
    print(f"Max current: {max_current*1e6:.1f}µA")
    print(f"Expected: {{}}, max = 100µA (default)")

    currents_match = currents == {}
    max_match = abs(max_current - 100e-6) < 1e-9  # Default 100µA

    print(f"✓ PASS" if currents_match and max_match else "✗ FAIL")
    print()

    return currents_match and max_match


def test_filter_tiny_currents():
    """Test that very small currents (< 1nA) are filtered out"""
    netlist = """
* Circuit with power current and tiny leakage current
VDD vdd 0 DC 1.8
Ibias bias 0 DC 100uA
Ileak leak 0 DC 0.1nA
M1 out bias 0 0 NMOS W=10u L=1u
RD vdd out 10k
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    currents = checker._extract_all_currents_from_netlist(netlist)
    max_current = checker._extract_max_current_from_netlist(netlist)

    print("=" * 70)
    print("Test 5: Filter Tiny Currents (<1nA)")
    print("=" * 70)
    print(f"All currents: {currents}")
    print(f"Max current: {max_current*1e6:.1f}µA")
    print(f"Expected: {{'bias': 100e-6}} (Ileak filtered out), max = 100µA")

    # Should only contain Ibias, not the tiny leakage current
    expected_currents = {'bias': 100e-6}
    currents_match = all(
        abs(currents.get(k, 0) - v) < 1e-12 for k, v in expected_currents.items()
    ) and len(currents) == len(expected_currents)
    max_match = abs(max_current - 100e-6) < 1e-9

    print(f"✓ PASS" if currents_match and max_match else "✗ FAIL")
    print()

    return currents_match and max_match


def test_wide_range_currents():
    """Test current sources spanning many orders of magnitude"""
    netlist = """
* Wide range of current values
VDD vdd 0 DC 5.0
Ihigh high 0 DC 10mA
Imed1 med1 0 DC 1mA
Imed2 med2 0 DC 100uA
Ilow low 0 DC 1uA
M1 out high 0 0 NMOS W=100u L=0.18u
.model NMOS NMOS (LEVEL=1 VTO=0.4)
"""
    checker = EquivalenceChecker()

    currents = checker._extract_all_currents_from_netlist(netlist)
    max_current = checker._extract_max_current_from_netlist(netlist)

    print("=" * 70)
    print("Test 6: Wide Range Currents (10mA → 1µA)")
    print("=" * 70)
    print(f"All currents: {currents}")
    print(f"Max current: {max_current*1e3:.1f}mA")

    expected_currents = {
        'high': 10e-3,
        'med1': 1e-3,
        'med2': 100e-6,
        'low': 1e-6
    }

    print(f"Expected: {expected_currents}, max = 10mA")

    currents_match = all(
        abs(currents.get(k, 0) - v) < 1e-12 for k, v in expected_currents.items()
    ) and len(currents) == len(expected_currents)

    max_match = abs(max_current - 10e-3) < 1e-9

    print(f"✓ PASS" if currents_match and max_match else "✗ FAIL")
    print()

    return currents_match and max_match


if __name__ == "__main__":
    print("\n")
    print("█" * 70)
    print("  MULTI-CURRENT SOURCE EXTRACTION TESTS")
    print("█" * 70)
    print("\n")

    results = []

    results.append(("Single Current Source (100µA)", test_single_current()))
    results.append(("Multiple Current Sources", test_multiple_currents()))
    results.append(("Various Units (mA, µA, nA, A)", test_various_units()))
    results.append(("No Current Sources (Default)", test_no_current_sources()))
    results.append(("Filter Tiny Currents", test_filter_tiny_currents()))
    results.append(("Wide Range Currents", test_wide_range_currents()))

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
