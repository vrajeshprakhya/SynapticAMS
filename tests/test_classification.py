#!/usr/bin/env python3
"""
Test the three-way circuit behavior classification
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from circuit_analyzer import parse_spice_netlist, build_bipartite_graph, analyze_blocks

# Test 1: Pure passive circuit (STRUCTURAL_LINEAR)
print("=" * 60)
print("TEST 1: Pure passive RC filter (STRUCTURAL_LINEAR)")
print("=" * 60)

netlist_passive = """
R1 vin vout 1k
C1 vout 0 1p
Vin vin 0 DC 0
"""

devices = parse_spice_netlist(netlist_passive)
G = build_bipartite_graph(devices)
blocks = analyze_blocks(G)

for b in blocks:
    print(f"\nBLOCK {b['block_id']}")
    print(f"  Behavior class: {b['behavior_class']}")
    print(f"  Simulation axes: {b['simulation_axes']}")
    print(f"  Outputs: {b['outputs']}")
    print(f"  Simulation plan:")
    for p in b['simulation_plan']:
        print(f"    {p}")

# Test 2: Source follower with resistor (SMALL_SIGNAL_LINEARIZABLE)
print("\n" + "=" * 60)
print("TEST 2: Source follower with resistor (SMALL_SIGNAL_LINEARIZABLE)")
print("=" * 60)

netlist_source_follower = """
M1 vdd vg vs 0 NMOS
RS vs 0 1k
VDD vdd 0 DC 1.8
Vin vg 0 DC 0
"""

devices = parse_spice_netlist(netlist_source_follower)
G = build_bipartite_graph(devices)
blocks = analyze_blocks(G)

for b in blocks:
    print(f"\nBLOCK {b['block_id']}")
    print(f"  Behavior class: {b['behavior_class']}")
    print(f"  Simulation axes: {b['simulation_axes']}")
    print(f"  Outputs: {b['outputs']}")
    print(f"  Simulation plan:")
    for p in b['simulation_plan']:
        print(f"    {p}")

# Test 3: Simple MOSFET with voltage source load (should be SMALL_SIGNAL too)
print("\n" + "=" * 60)
print("TEST 3: Common-source with resistive load (SMALL_SIGNAL_LINEARIZABLE)")
print("=" * 60)

netlist_common_source = """
M1 vd vg 0 0 NMOS
RD vdd vd 10k
VDD vdd 0 DC 1.8
Vin vg 0 DC 0
"""

devices = parse_spice_netlist(netlist_common_source)
G = build_bipartite_graph(devices)
blocks = analyze_blocks(G)

for b in blocks:
    print(f"\nBLOCK {b['block_id']}")
    print(f"  Behavior class: {b['behavior_class']}")
    print(f"  Simulation axes: {b['simulation_axes']}")
    print(f"  Outputs: {b['outputs']}")
    print(f"  Simulation plan:")
    for p in b['simulation_plan']:
        print(f"    {p}")

# Test 4: Direct MOSFET without passive (currently NONLINEAR, but could be SMALL_SIGNAL)
print("\n" + "=" * 60)
print("TEST 4: Simple MOSFET with voltage source (edge case)")
print("=" * 60)

netlist_simple = """
M1 vd vg 0 0 NMOS
VDD vd 0 DC 1.8
Vin vg 0 DC 0
"""

devices = parse_spice_netlist(netlist_simple)
G = build_bipartite_graph(devices)
blocks = analyze_blocks(G)

for b in blocks:
    print(f"\nBLOCK {b['block_id']}")
    print(f"  Behavior class: {b['behavior_class']}")
    print(f"  Simulation axes: {b['simulation_axes']}")
    print(f"  Outputs: {b['outputs']}")
    print(f"  Simulation plan:")
    for p in b['simulation_plan']:
        print(f"    {p}")
