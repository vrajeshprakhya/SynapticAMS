#!/usr/bin/env python3
"""
Debug the differential pair block detection
"""

from graph_builder import parse_spice_netlist, build_bipartite_graph
from circuit_analyzer import analyze_blocks, find_constant_nets, find_control_relevant_devices

# Read the differential pair netlist
with open('/home/vrajeshprakhya/circuit_preprocess/test_diffpair.cir', 'r') as f:
    netlist_text = f.read()

# Parse and build graph
devices = parse_spice_netlist(netlist_text)
graph = build_bipartite_graph(devices)

print("=" * 80)
print("DEVICES:")
print("=" * 80)
for d in devices:
    print(f"{d['name']}: type={d['type']}, nets={d['nets']}")
    if 'raw' in d:
        print(f"  raw: {d['raw']}")

print("\n" + "=" * 80)
print("CONSTANT NETS:")
print("=" * 80)
constant_nets = find_constant_nets(graph)
print(constant_nets)

print("\n" + "=" * 80)
print("CONTROL RELEVANT DEVICES:")
print("=" * 80)
control_devices = find_control_relevant_devices(graph)
print(control_devices)

from circuit_analyzer import find_control_terminal_nets
print("\n" + "=" * 80)
print("CONTROL TERMINAL NETS:")
print("=" * 80)
control_terminal_nets = find_control_terminal_nets(control_devices, graph)
print(control_terminal_nets)

print("\n" + "=" * 80)
print("BLOCKS:")
print("=" * 80)
blocks = analyze_blocks(graph)

for i, block in enumerate(blocks):
    print(f"\nBLOCK {i}:")
    print(f"  Behavior: {block['behavior_class']}")
    print(f"  Inputs: {block['inputs']}")
    print(f"  Outputs: {block['outputs']}")
    print(f"  Control axes: {block['simulation_axes']}")
    print(f"  Nodes in block:")
    for node in sorted(block['nodes']):
        node_data = graph.nodes[node]
        if node_data['kind'] == 'device':
            print(f"    {node} ({node_data['device_type']})")
        else:
            print(f"    {node} (net)")
