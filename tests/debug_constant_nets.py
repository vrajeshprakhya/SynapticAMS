#!/usr/bin/env python3
"""
Debug constant net detection
"""

from graph_builder import parse_spice_netlist, build_bipartite_graph

netlist = """
* Common source amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

devices = parse_spice_netlist(netlist)
graph = build_bipartite_graph(devices)

# Manually check net:0 (ground)
print("Checking net:0 (ground):")
net = "net:0"
print(f"  Neighbors: {list(graph[net])}")

for neighbor in graph[net]:
    print(f"\n  Device: {neighbor}")
    print(f"    Device data: {graph.nodes[neighbor]}")
    edge_data = graph[net][neighbor]
    print(f"    Edge data: {edge_data}")

# Check net:vdd (power)
print("\n" + "="*60)
print("Checking net:vdd (power rail):")
net = "net:vdd"
print(f"  Neighbors: {list(graph[net])}")

for neighbor in graph[net]:
    print(f"\n  Device: {neighbor}")
    print(f"    Device data: {graph.nodes[neighbor]}")
    edge_data = graph[net][neighbor]
    print(f"    Edge data: {edge_data}")

# Check net:vin (input - should NOT be constant)
print("\n" + "="*60)
print("Checking net:vin (input - should NOT be constant):")
net = "net:vin"
print(f"  Neighbors: {list(graph[net])}")

for neighbor in graph[net]:
    print(f"\n  Device: {neighbor}")
    print(f"    Device data: {graph.nodes[neighbor]}")
    edge_data = graph[net][neighbor]
    print(f"    Edge data: {edge_data}")

# Check net:vout (output - should NOT be constant)
print("\n" + "="*60)
print("Checking net:vout (output - should NOT be constant):")
net = "net:vout"
print(f"  Neighbors: {list(graph[net])}")

for neighbor in graph[net]:
    print(f"\n  Device: {neighbor}")
    print(f"    Device data: {graph.nodes[neighbor]}")
    edge_data = graph[net][neighbor]
    print(f"    Edge data: {edge_data}")
