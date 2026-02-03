#!/usr/bin/env python3
"""
Combined Circuit Analyzer + Simulation Planning

Pipeline:
1. Parse SPICE netlist
2. Build bipartite graph (devices <-> nets)
3. Detect constant nets
4. Detect control-relevant devices + control terminals
5. Build full signal graph (remove constant nets only)
6. Extract blocks (connected components)
7. Extract block IO (topology-only)
8. Derive simulation axes (IO ∩ control terminals)
9. Classify circuit behavior (3-way: STRUCTURAL_LINEAR / SMALL_SIGNAL_LINEARIZABLE / NONLINEAR)
10. Plan simulations based on behavior class
"""

import networkx as nx
import re

# ============================================================
# Device definitions
# ============================================================

DEVICE_TERMINALS = {
    "M": ["D", "G", "S", "B"],
    "Q": ["C", "B", "E"],
    "R": ["1", "2"],
    "C": ["1", "2"],
    "L": ["1", "2"],
    "V": ["+", "-"],
    "I": ["+", "-"],
}

CONTROL_PINS = {
    "M": {"G"},
    "Q": {"B"},
}

ACTIVE_OUTPUT_PINS = {
    "M": {"D", "S"},
    "Q": {"C", "E"},
}

# Pins that propagate signals (exclude bulk/substrate)
SIGNAL_PINS = {
    "M": {"G", "D", "S"},  # Exclude B (bulk)
    "Q": {"B", "C", "E"},  # All pins for BJT
}

PASSIVE_DEVICES = {"R", "C", "L"}

# ============================================================
# SPICE netlist parser
# ============================================================

def parse_spice_netlist(netlist_text):
    devices = []

    for line in netlist_text.splitlines():
        line = line.strip()
        if not line or line.startswith("*") or line.startswith("."):
            continue

        tokens = re.split(r"\s+", line)
        dev_name = tokens[0]
        dev_type = dev_name[0].upper()

        if dev_type not in DEVICE_TERMINALS:
            continue

        terminals = DEVICE_TERMINALS[dev_type]
        nets = tokens[1:1 + len(terminals)]

        devices.append({
            "name": dev_name,
            "type": dev_type,
            "nets": dict(zip(terminals, nets)),
        })

    return devices

# ============================================================
# Bipartite graph builder
# ============================================================

def build_bipartite_graph(devices):
    G = nx.Graph()

    for dev in devices:
        dev_node = f"dev:{dev['name']}"
        G.add_node(dev_node, kind="device", device_type=dev["type"])

        for terminal, net in dev["nets"].items():
            net_node = f"net:{net}"
            G.add_node(net_node, kind="net")
            G.add_edge(dev_node, net_node, terminal=terminal)

    return G

# ============================================================
# Constant net detection
# ============================================================

def is_constant_net(net, graph):
    visited = set()
    stack = [net]

    while stack:
        n = stack.pop()
        if n in visited:
            continue
        visited.add(n)

        for dev, edge_data in graph[n].items():
            dtype = graph.nodes[dev]["device_type"]
            pin = edge_data["terminal"]

            if dtype == "V":
                # Check if this is a signal source (AC/transient) or power supply (DC only)
                raw_line = graph.nodes[dev].get("raw", "").lower()
                # Signal sources have ac, sin, pulse, pwl, etc. - they are NOT constant
                is_signal_source = any(keyword in raw_line for keyword in
                                      ["ac ", "sin", "pulse", "pwl", "sffm", "exp"])
                if is_signal_source:
                    # This net is driven by a time-varying signal - NOT constant
                    return False
                # Power supply (DC only) - continue traversal
                continue

            if dtype in PASSIVE_DEVICES:
                for other in graph[dev]:
                    if other != n:
                        stack.append(other)
                continue

            if pin in ACTIVE_OUTPUT_PINS.get(dtype, set()):
                return False

            # Only traverse through signal-carrying pins (not bulk/substrate)
            if pin in SIGNAL_PINS.get(dtype, set()):
                for other in graph[dev]:
                    if other != n:
                        stack.append(other)

    return True

def find_constant_nets(graph):
    return {
        n for n, d in graph.nodes(data=True)
        if d["kind"] == "net" and is_constant_net(n, graph)
    }

# ============================================================
# Control relevance
# ============================================================

def find_control_relevant_devices(graph):
    devices = set()
    for d, data in graph.nodes(data=True):
        if data["kind"] != "device":
            continue
        dtype = data["device_type"]
        for net, edge_data in graph[d].items():
            if edge_data["terminal"] in CONTROL_PINS.get(dtype, set()):
                if not is_constant_net(net, graph):
                    devices.add(d)
    return devices

def find_control_terminal_nets(control_devices, graph):
    nets = set()
    for dev in control_devices:
        dtype = graph.nodes[dev]["device_type"]
        for net, edge_data in graph[dev].items():
            if edge_data["terminal"] in CONTROL_PINS.get(dtype, set()):
                nets.add(net)
    return nets

def find_signal_source_nets(graph):
    """Find nets connected to signal voltage/current sources (AC/transient sources)."""
    signal_nets = set()
    for node, data in graph.nodes(data=True):
        if data["kind"] == "device" and data.get("device_type") in {"V", "I"}:
            # Check if it's a signal source
            raw_line = data.get("raw", "").lower()
            is_signal = any(keyword in raw_line for keyword in
                          ["ac ", "sin", "pulse", "pwl", "sffm", "exp"])
            if is_signal:
                # Add all nets connected to this source
                for neighbor in graph[node]:
                    if graph.nodes[neighbor]["kind"] == "net":
                        signal_nets.add(neighbor)
    return signal_nets

# ============================================================
# Full signal graph
# ============================================================

def build_full_signal_graph(graph, constant_nets):
    G = nx.Graph()

    for node, data in graph.nodes(data=True):
        # Skip constant nets
        if data["kind"] == "net" and node in constant_nets:
            continue

        # Skip voltage/current sources (they're external stimuli, not circuit behavior)
        if data["kind"] == "device" and data.get("device_type") in {"V", "I"}:
            continue

        G.add_node(node, **data)

    for u, v in graph.edges():
        if u in G and v in G:
            G.add_edge(u, v)

    return G

# ============================================================
# Block extraction
# ============================================================

def extract_blocks(signal_graph):
    return list(nx.connected_components(signal_graph))

# ============================================================
# Block IO
# ============================================================

def extract_block_io(block_nodes, graph):
    inputs = set()
    outputs = set()
    block_nodes = set(block_nodes)

    for node in block_nodes:
        if graph.nodes[node]["kind"] != "net":
            continue

        for dev, edge_data in graph[node].items():
            dtype = graph.nodes[dev]["device_type"]
            pin = edge_data["terminal"]

            if dev not in block_nodes:
                # External device connected to this net

                # Voltage/current sources are always inputs to the circuit
                if dtype in {"V", "I"}:
                    inputs.add(node)
                    continue

                if pin in CONTROL_PINS.get(dtype, set()):
                    inputs.add(node)
                if pin in ACTIVE_OUTPUT_PINS.get(dtype, set()):
                    outputs.add(node)
            else:
                # Internal device - mark nets connected to active outputs as observable
                if pin in ACTIVE_OUTPUT_PINS.get(dtype, set()):
                    outputs.add(node)

    return inputs, outputs

# ============================================================
# Circuit behavior classification (3-way)
# ============================================================
# Three distinct classes:
# 1. STRUCTURAL_LINEAR: Pure passive (R/L/C) - already linear
# 2. SMALL_SIGNAL_LINEARIZABLE: Has transistors but linearizable around OP
# 3. NONLINEAR: Switching, limiting, or strongly nonlinear behavior

def path_has_passive(path, graph):
    for node in path:
        if graph.nodes[node]["kind"] == "device":
            if graph.nodes[node]["device_type"] in PASSIVE_DEVICES:
                return True
    return False

def has_active_devices(block_graph):
    """Check if block contains any active devices (MOSFETs, BJTs)."""
    for node in block_graph.nodes():
        if block_graph.nodes[node].get("kind") == "device":
            dev_type = block_graph.nodes[node].get("device_type")
            if dev_type in {"M", "Q"}:
                return True
    return False

def has_passive_at_output(output_net, block_graph):
    """Check if output net has passive elements (load resistors, capacitors) connected."""
    if output_net not in block_graph:
        return False

    for neighbor in block_graph[output_net]:
        if block_graph.nodes[neighbor].get("kind") == "device":
            dev_type = block_graph.nodes[neighbor].get("device_type")
            if dev_type in PASSIVE_DEVICES:
                return True
    return False

def is_small_signal_linearizable(block_graph, simulation_axes, outputs):
    """
    Determine if a circuit with active devices is suitable for small-signal analysis.

    Key insight: Most analog amplifier circuits (source followers, diff pairs, OTAs)
    ARE linearizable, even though they contain nonlinear devices.

    Heuristics:
    1. If most signal paths include passive elements (R/L/C), it suggests
       analog amplification rather than digital switching
    2. If outputs have passive loads (resistors, capacitors), it indicates
       analog amplification (common-source, common-emitter, etc.)
    3. Passive elements typically indicate biasing, feedback, or load networks

    These are characteristic of linearizable analog circuits.
    """
    if not simulation_axes or not outputs:
        return False

    # Heuristic 1: Check paths from control to output
    paths_with_passive = 0
    total_paths = 0

    for ctrl in simulation_axes:
        for out in outputs:
            try:
                paths = list(nx.all_simple_paths(block_graph, ctrl, out, cutoff=6))
                for path in paths:
                    total_paths += 1
                    if path_has_passive(path, block_graph):
                        paths_with_passive += 1
            except nx.NetworkXNoPath:
                continue

    # Heuristic 2: Check if outputs have passive loads
    outputs_with_passive = sum(1 for out in outputs if has_passive_at_output(out, block_graph))

    # Linearizable if:
    # - Most paths have passives (source follower, degenerated amp), OR
    # - Most outputs have passive loads (common-source, common-emitter), OR
    # - At least some combination of both
    if total_paths > 0:
        path_score = paths_with_passive / total_paths
    else:
        path_score = 0

    if len(outputs) > 0:
        output_score = outputs_with_passive / len(outputs)
    else:
        output_score = 0

    # Linearizable if either score is reasonably high, or if combined they suggest analog behavior
    # This catches: source followers (high path_score), common-source amps (high output_score),
    # and more complex circuits with some of both
    return (path_score > 0.3) or (output_score > 0.5) or (path_score + output_score > 0.6)

def classify_circuit_behavior(block_graph, simulation_axes, outputs):
    """
    Classify circuit behavior into one of three categories:

    Returns:
        'STRUCTURAL_LINEAR': Pure passive circuit (R/L/C only)
                           - Already linear for all amplitudes
                           - No gm/gds parameters
                           - Extract via symbolic MNA/Laplace

        'SMALL_SIGNAL_LINEARIZABLE': Contains transistors but linearizable
                                    - Physically nonlinear but locally linear
                                    - Has gm/gds parameters at operating point
                                    - Extract via DC OP → small-signal stamping
                                    - Examples: source followers, diff pairs, OTAs

        'NONLINEAR': Strongly nonlinear, switching, or limiting behavior
                    - Cannot linearize around single operating point
                    - Requires piecewise, LUT, or nonlinear models
                    - Examples: comparators, switches, rail-to-rail buffers
    """
    # Check for active devices in the block
    has_active = has_active_devices(block_graph)

    if not has_active:
        # Pure passive circuit - structurally linear
        return 'STRUCTURAL_LINEAR'

    # Has active devices - check if linearizable
    if is_small_signal_linearizable(block_graph, simulation_axes, outputs):
        # Most common case: analog amplifiers, buffers, filters with active elements
        return 'SMALL_SIGNAL_LINEARIZABLE'
    else:
        # Switching, comparator, or other strongly nonlinear behavior
        return 'NONLINEAR'

# ============================================================
# Simulation planning (behavior-aware)
# ============================================================

def plan_dc_simulations(block):
    """
    Plan simulation strategy based on circuit behavior classification.

    STRUCTURAL_LINEAR:
        - No DC operating point needed
        - Direct AC/frequency analysis
        - Symbolic MNA extraction

    SMALL_SIGNAL_LINEARIZABLE:
        - DC OP extraction required
        - Extract gm/gds at operating point
        - 1D independent sweeps to build transfer function
        - This is the MAIN use case for most analog circuits

    NONLINEAR:
        - Multi-dimensional sweeps or region-aware analysis
        - May need piecewise or LUT-based models
    """
    plans = []

    if not block["simulation_axes"] or not block["outputs"]:
        return plans

    behavior = block["behavior_class"]

    if behavior == "STRUCTURAL_LINEAR":
        # Pure passive circuit - already linear
        plans.append({
            "type": "ac_analysis",
            "sweep_net": list(block["simulation_axes"]),
            "observe": list(block["outputs"]),
            "strategy": "symbolic MNA - no DC OP needed",
            "extract_gm": False,
            "needs_dc_op": False
        })

    elif behavior == "SMALL_SIGNAL_LINEARIZABLE":
        # Most analog circuits land here: source followers, diff pairs, OTAs
        # Need DC OP first, then small-signal extraction
        plans.append({
            "type": "dc_op",
            "strategy": "find operating point for linearization",
            "extract_gm": True,
            "needs_dc_op": True
        })

        # Then sweep each axis independently to build transfer function
        for axis in block["simulation_axes"]:
            plans.append({
                "type": "dc_sweep",
                "sweep_net": axis,
                "observe": list(block["outputs"]),
                "strategy": "1D independent sweep around OP",
                "extract_gm": True,
                "needs_dc_op": True
            })

    else:  # NONLINEAR
        # Multi-dimensional or region-aware analysis required
        plans.append({
            "type": "dc_sweep",
            "sweep_net": list(block["simulation_axes"]),
            "observe": list(block["outputs"]),
            "strategy": "multi-dimensional sweep or piecewise model",
            "extract_gm": False,
            "needs_dc_op": True
        })

    return plans

# ============================================================
# High-level analysis
# ============================================================

def analyze_blocks(graph):
    constant_nets = find_constant_nets(graph)
    control_devices = find_control_relevant_devices(graph)
    control_terminal_nets = find_control_terminal_nets(control_devices, graph)
    signal_source_nets = find_signal_source_nets(graph)

    signal_graph = build_full_signal_graph(graph, constant_nets)
    blocks = extract_blocks(signal_graph)

    results = []

    for i, block_nodes in enumerate(blocks):
        inputs, outputs = extract_block_io(block_nodes, graph)
        # Control axes are signal source nets that are inputs to this block
        sim_axes = inputs & signal_source_nets

        block_graph = signal_graph.subgraph(block_nodes)

        # Three-way classification instead of boolean
        behavior_class = classify_circuit_behavior(
            block_graph, sim_axes, outputs
        )

        block_info = {
            "block_id": i,
            "nodes": block_nodes,
            "inputs": inputs,
            "outputs": outputs,
            "simulation_axes": sim_axes,
            "behavior_class": behavior_class,
            # Keep linear_intent for backwards compatibility (deprecated)
            "linear_intent": behavior_class in ["STRUCTURAL_LINEAR", "SMALL_SIGNAL_LINEARIZABLE"],
        }

        block_info["simulation_plan"] = plan_dc_simulations(block_info)

        results.append(block_info)

    return results

# ============================================================
# Example
# ============================================================

if __name__ == "__main__":
    spice_netlist = """
    M1 vd vg 0 0 NMOS
    VDD vd 0 DC 1.8
    Vin vg 0 DC 0
    """

    devices = parse_spice_netlist(spice_netlist)
    G = build_bipartite_graph(devices)

    blocks = analyze_blocks(G)

    for b in blocks:
        print("\nBLOCK", b["block_id"])
        print(" Behavior class:", b["behavior_class"])
        print(" Linear intent (deprecated):", b["linear_intent"])
        print(" Simulation axes:", b["simulation_axes"])
        print(" Outputs:", b["outputs"])
        print(" Simulation plan:")
        for p in b["simulation_plan"]:
            print("  ", p)

