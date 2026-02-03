#!/usr/bin/env python3
"""
simulation_planner.py

Converts structural analysis results into concrete ngspice simulation parameters.

Input:  Block analysis from circuit_analyzer.py
Output: Detailed simulation plans with sweep ranges, step sizes, etc.
"""

import re


class SimulationPlanner:
    """
    Plans concrete simulation parameters based on circuit topology
    """

    def __init__(self, graph, constant_nets):
        """
        Args:
            graph: Bipartite graph from circuit_analyzer
            constant_nets: Set of constant net nodes
        """
        self.graph = graph
        self.constant_nets = constant_nets
        self.vdd = self._extract_supply_voltage()

    def _extract_supply_voltage(self):
        """
        Extract VDD from voltage sources in constant nets

        Returns:
            float: Supply voltage (default 1.8V if not found)
        """
        for node in self.constant_nets:
            # Look for voltage source devices connected to this net
            if node not in self.graph:
                continue

            for dev, edge_data in self.graph[node].items():
                if self.graph.nodes[dev].get("kind") != "device":
                    continue

                dtype = self.graph.nodes[dev].get("device_type")

                # Found a voltage source
                if dtype == "V":
                    # Try to extract voltage from raw SPICE line
                    raw = self.graph.nodes[dev].get("raw", "")

                    # Parse: VDD vdd 0 DC 1.8V
                    match = re.search(r'DC\s+([\d.]+)', raw, re.IGNORECASE)
                    if match:
                        voltage = float(match.group(1))
                        if voltage > 0.5:  # Filter out ground
                            return voltage

        # Default if not found
        return 1.8

    def _is_gate_net(self, net):
        """Check if net connects to MOSFET gate"""
        if net not in self.graph:
            return False

        for dev, edge_data in self.graph[net].items():
            if self.graph.nodes[dev].get("kind") != "device":
                continue

            dtype = self.graph.nodes[dev].get("device_type")
            terminal = edge_data.get("terminal")

            if dtype == "M" and terminal == "G":
                return True

        return False

    def _is_base_net(self, net):
        """Check if net connects to BJT base"""
        if net not in self.graph:
            return False

        for dev, edge_data in self.graph[net].items():
            if self.graph.nodes[dev].get("kind") != "device":
                continue

            dtype = self.graph.nodes[dev].get("device_type")
            terminal = edge_data.get("terminal")

            if dtype == "Q" and terminal == "B":
                return True

        return False

    def _is_differential_pair(self, net):
        """
        Heuristic: Check if net is part of differential pair

        Simple heuristic: If two similar devices (same type) both connect
        their gates/bases to different nets in the same block
        """
        # This is a simplified heuristic
        # More sophisticated: check for symmetric topology

        if net not in self.graph:
            return False

        # Count MOSFET gates or BJT bases connected to this net
        control_devices = []

        for dev, edge_data in self.graph[net].items():
            if self.graph.nodes[dev].get("kind") != "device":
                continue

            dtype = self.graph.nodes[dev].get("device_type")
            terminal = edge_data.get("terminal")

            if (dtype == "M" and terminal == "G") or (dtype == "Q" and terminal == "B"):
                control_devices.append(dev)

        # If multiple devices share this control net, likely not differential
        # Differential pairs have separate control inputs
        return len(control_devices) == 1

    def determine_sweep_range(self, net):
        """
        Determine appropriate sweep range for a net

        Args:
            net: Net node name (e.g., "net:vg")

        Returns:
            tuple: (start, stop) voltage range
        """
        # Extract actual net name (remove "net:" prefix if present)
        net_name = net.replace("net:", "")

        # Check device connections to determine range
        if self._is_gate_net(net):
            # MOSFET gate: 0 to VDD
            return (0.0, self.vdd)

        elif self._is_base_net(net):
            # BJT base: 0 to ~0.9V (typical BJT range)
            return (0.0, min(0.9, self.vdd))

        elif self._is_differential_pair(net):
            # Differential input: symmetric around 0
            return (-self.vdd / 2, self.vdd / 2)

        else:
            # Default: 0 to VDD
            return (0.0, self.vdd)

    def determine_step_size(self, start, stop, linear_intent=None, behavior_class=None):
        """
        Determine appropriate step size for sweep

        Args:
            start, stop: Sweep range
            linear_intent: Boolean indicating if block is linear (deprecated, for backwards compat)
            behavior_class: String classification ('STRUCTURAL_LINEAR', 'SMALL_SIGNAL_LINEARIZABLE', 'NONLINEAR')

        Returns:
            float: Step size
        """
        span = stop - start

        # Use behavior_class if provided, otherwise fall back to linear_intent
        if behavior_class is not None:
            if behavior_class == "STRUCTURAL_LINEAR":
                # Pure passive: very smooth, need fewest points
                return span / 20
            elif behavior_class == "SMALL_SIGNAL_LINEARIZABLE":
                # Linearizable around OP: moderate resolution to capture curvature
                return span / 30
            else:  # NONLINEAR
                # Strongly nonlinear: need fine resolution near thresholds
                return span / 50
        else:
            # Backwards compatibility path
            if linear_intent:
                # Linear circuits: 20-30 points sufficient
                return span / 25
            else:
                # Nonlinear circuits: need finer resolution
                return span / 50

    def plan_dc_sweep(self, block):
        """
        Generate concrete DC sweep parameters for a block

        Args:
            block: Block dict from circuit_analyzer with:
                   - simulation_axes: set of control nets
                   - outputs: set of output nets
                   - behavior_class: str (STRUCTURAL_LINEAR/SMALL_SIGNAL_LINEARIZABLE/NONLINEAR)
                   - linear_intent: bool (deprecated, for backwards compatibility)

        Returns:
            list: List of sweep parameter dicts
        """
        sweep_plans = []

        simulation_axes = block.get('simulation_axes', set())
        outputs = block.get('outputs', set())
        behavior_class = block.get('behavior_class')
        linear_intent = block.get('linear_intent', False)

        if not simulation_axes or not outputs:
            # No controllable inputs or no outputs - can't sweep
            return sweep_plans

        # For each control axis, create a sweep plan
        for net in simulation_axes:
            start, stop = self.determine_sweep_range(net)
            step = self.determine_step_size(start, stop, linear_intent, behavior_class)

            # Convert net node names to actual net names for SPICE
            # Remove "net:" prefix
            sweep_var = net.replace("net:", "")
            observe_vars = [n.replace("net:", "") for n in outputs]

            sweep_plans.append({
                'type': 'dc_sweep',
                'sweep_var': sweep_var,
                'start': start,
                'stop': stop,
                'step': step,
                'observe': observe_vars,
                'behavior_class': behavior_class,
                'linear_intent': linear_intent  # Keep for backwards compat
            })

        return sweep_plans

    def plan_dc_op(self, block):
        """
        Generate DC operating point analysis parameters

        Args:
            block: Block dict from circuit_analyzer

        Returns:
            dict: DC OP parameters
        """
        outputs = block.get('outputs', set())
        observe_vars = [n.replace("net:", "") for n in outputs]

        return {
            'type': 'dc_op',
            'observe': observe_vars
        }


# Example usage
if __name__ == "__main__":
    # This would normally come from circuit_analyzer.py
    import networkx as nx
    from graph_builder import parse_spice_netlist, build_bipartite_graph
    from circuit_analyzer import analyze_blocks

    # Example netlist
    spice_netlist = """
    M1 vd vg 0 0 NMOS W=1u L=1u
    VDD vd 0 DC 1.8V
    Vin vg 0 DC 0V
    """

    # Build graph and analyze
    from graph_builder import parse_spice_netlist, build_bipartite_graph
    devices = parse_spice_netlist(spice_netlist)
    graph = build_bipartite_graph(devices)

    # Analyze (this would use circuit_analyzer.py)
    from circuit_analyzer import analyze_blocks, find_constant_nets
    constant_nets = find_constant_nets(graph)
    blocks = analyze_blocks(graph)

    # Create planner
    planner = SimulationPlanner(graph, constant_nets)

    # Generate sweep plans
    for block in blocks:
        print(f"\n=== BLOCK {block['block_id']} ===")
        print(f"Behavior class: {block.get('behavior_class', 'N/A')}")
        print(f"Linear intent (deprecated): {block['linear_intent']}")
        print(f"Simulation axes: {block['simulation_axes']}")
        print(f"Outputs: {block['outputs']}")

        sweep_plans = planner.plan_dc_sweep(block)

        print(f"\nSweep plans:")
        for plan in sweep_plans:
            print(f"  Sweep {plan['sweep_var']} from {plan['start']:.2f}V to {plan['stop']:.2f}V")
            print(f"  Step: {plan['step']:.4f}V")
            print(f"  Observe: {plan['observe']}")
