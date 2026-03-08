#!/usr/bin/env python3
"""
Debug script to understand what circuit_analyzer is finding
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from graph_builder import parse_spice_netlist, build_bipartite_graph
from circuit_analyzer import (
    find_constant_nets,
    find_control_relevant_devices,
    find_control_terminal_nets,
    build_full_signal_graph,
    extract_blocks
)

netlist = """
* Common source amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

print("Parsing netlist...")
devices = parse_spice_netlist(netlist)
print(f"Devices: {[d['name'] for d in devices]}\n")

print("Building graph...")
graph = build_bipartite_graph(devices)

print("All nodes in graph:")
for node, data in graph.nodes(data=True):
    print(f"  {node}: {data}")

print("\n" + "="*60)
print("Finding constant nets...")
constant_nets = find_constant_nets(graph)
print(f"Constant nets: {constant_nets}\n")

print("="*60)
print("Finding control-relevant devices...")
control_devices = find_control_relevant_devices(graph)
print(f"Control-relevant devices: {control_devices}\n")

print("="*60)
print("Finding control terminal nets...")
control_terminal_nets = find_control_terminal_nets(control_devices, graph)
print(f"Control terminal nets: {control_terminal_nets}\n")

print("="*60)
print("Building signal graph (removing constant nets)...")
signal_graph = build_full_signal_graph(graph, constant_nets)
print(f"Signal graph nodes: {list(signal_graph.nodes())}")
print(f"Signal graph edges: {list(signal_graph.edges())}\n")

print("="*60)
print("Extracting blocks...")
blocks = extract_blocks(signal_graph)
print(f"Found {len(blocks)} blocks")
for i, block in enumerate(blocks):
    print(f"\nBlock {i}:")
    print(f"  Nodes: {block}")
