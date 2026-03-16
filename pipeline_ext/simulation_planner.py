#!/usr/bin/env python3
"""
simulation_planner.py

Converts structural analysis results into concrete ngspice simulation parameters.

Input:  Block analysis from pipeline_ext.circuit_analyzer.py
Output: Detailed simulation plans with sweep ranges, step sizes, etc.

NEW: Automatically detects multi-input circuits and determines if 2D sweeps are needed
     by testing source coupling using simulation-based empirical analysis.
"""

import re
from equivalence_checker.independence_detector import test_source_independence


class SimulationPlanner:
    """
    Plans concrete simulation parameters based on circuit topology
    """

    def __init__(self, graph, constant_nets, netlist=None, runner=None):
        """
        Args:
            graph: Bipartite graph from pipeline_ext.circuit_analyzer
            constant_nets: Set of constant net nodes
            netlist: SPICE netlist as string (optional, needed for independence detection)
            runner: NgspiceRunner instance (optional, created if not provided)
        """
        self.graph = graph
        self.constant_nets = constant_nets
        self.netlist = netlist
        self.runner = runner
        self.vdd = self._extract_supply_voltage()

        # Flag to enable/disable independence detection
        # Set to False to use legacy behavior (always generate separate 1D sweeps)
        self.enable_independence_detection = (netlist is not None)

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

        NEW: Automatically detects if 2D sweep is needed for multi-input blocks

        Args:
            block: Block dict from pipeline_ext.circuit_analyzer with:
                   - simulation_axes: set of control nets
                   - outputs: set of output nets
                   - behavior_class: str (STRUCTURAL_LINEAR/SMALL_SIGNAL_LINEARIZABLE/NONLINEAR)
                   - linear_intent: bool (deprecated, for backwards compatibility)

        Returns:
            list: List of sweep parameter dicts
                  - For single input or independent inputs: multiple 1D sweep dicts
                  - For coupled inputs: single 2D sweep dict
        """
        simulation_axes = block.get('simulation_axes', set())
        outputs = block.get('outputs', set())
        behavior_class = block.get('behavior_class')
        linear_intent = block.get('linear_intent', False)

        if not simulation_axes or not outputs:
            # No controllable inputs or no outputs - can't sweep
            return []

        # Convert sets to lists for easier handling
        axes_list = list(simulation_axes)
        outputs_list = list(outputs)

        # Single input: use traditional 1D sweep
        if len(axes_list) == 1:
            return self._plan_1d_sweeps(axes_list, outputs_list, behavior_class, linear_intent)

        # Multiple inputs: check if independence detection is enabled
        if not self.enable_independence_detection:
            # Legacy behavior: always generate separate 1D sweeps
            return self._plan_1d_sweeps(axes_list, outputs_list, behavior_class, linear_intent)

        # Test for coupling
        print(f"      [Independence Detection] Testing {len(axes_list)} inputs for coupling...")
        coupling_result = self._test_source_coupling(axes_list, outputs_list)

        if coupling_result['coupled']:
            # Sources are coupled → need 2D sweep
            print(f"      → Sources are COUPLED (strength={coupling_result['coupling_strength']:.3f})")
            print(f"      → Generating 2D sweep")
            return self._plan_2d_sweep(axes_list, outputs_list, behavior_class,
                                       linear_intent, coupling_result)
        else:
            # Sources are independent → separate 1D sweeps OK
            print(f"      → Sources are INDEPENDENT (strength={coupling_result['coupling_strength']:.3f})")
            print(f"      → Generating {len(axes_list)} separate 1D sweeps")
            return self._plan_1d_sweeps(axes_list, outputs_list, behavior_class, linear_intent)

    def _plan_1d_sweeps(self, simulation_axes, outputs, behavior_class, linear_intent):
        """
        Generate separate 1D sweep plans for each input

        Args:
            simulation_axes: List of control net names
            outputs: List of output net names
            behavior_class: Block behavior classification
            linear_intent: Legacy linear flag

        Returns:
            list: List of 1D sweep parameter dicts
        """
        sweep_plans = []

        # Filter out ground and other non-sweepable nets
        ground_nets = {'net:0', 'net:gnd', 'net:GND'}
        sweepable_axes = [net for net in simulation_axes if net not in ground_nets]

        for net in sweepable_axes:
            start, stop = self.determine_sweep_range(net)
            step = self.determine_step_size(start, stop, linear_intent, behavior_class)

            # Convert net node names to actual net names for SPICE
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
                'linear_intent': linear_intent
            })

        return sweep_plans

    def _plan_2d_sweep(self, simulation_axes, outputs, behavior_class,
                       linear_intent, coupling_info):
        """
        Generate 2D sweep plan for coupled inputs

        Args:
            simulation_axes: List of control net names (at least 2)
            outputs: List of output net names
            behavior_class: Block behavior classification
            linear_intent: Legacy linear flag
            coupling_info: Dict with coupling test results

        Returns:
            list: Single-element list with 2D sweep parameter dict
        """
        # Filter out ground
        ground_nets = {'net:0', 'net:gnd', 'net:GND'}
        sweepable_axes = [net for net in simulation_axes if net not in ground_nets]

        if len(sweepable_axes) < 2:
            # Not enough sweepable inputs, fall back to 1D
            return self._plan_1d_sweeps(sweepable_axes, outputs, behavior_class, linear_intent)

        # Use first two sources for 2D sweep
        # TODO: Handle >2 inputs (would need 3D, 4D sweeps or pairwise analysis)
        src1 = sweepable_axes[0]
        src2 = sweepable_axes[1]

        # Determine ranges
        start1, stop1 = self.determine_sweep_range(src1)
        start2, stop2 = self.determine_sweep_range(src2)

        # Use coarser step size for 2D sweeps (computational cost is N^2)
        # Aim for ~10x10 grid instead of 50x50
        step1 = self.determine_step_size(start1, stop1, linear_intent, behavior_class) * 5
        step2 = self.determine_step_size(start2, stop2, linear_intent, behavior_class) * 5

        # Convert to SPICE names
        sweep_var1 = src1.replace("net:", "")
        sweep_var2 = src2.replace("net:", "")
        observe_vars = [n.replace("net:", "") for n in outputs]

        return [{
            'type': 'dc_sweep_2d',
            'sweep_var_1': sweep_var1,
            'start_1': start1,
            'stop_1': stop1,
            'step_1': step1,
            'sweep_var_2': sweep_var2,
            'start_2': start2,
            'stop_2': stop2,
            'step_2': step2,
            'observe': observe_vars,
            'behavior_class': behavior_class,
            'linear_intent': linear_intent,
            'coupling_info': coupling_info
        }]

    def _test_source_coupling(self, simulation_axes, outputs):
        """
        Test if multiple sources are coupled using simulation

        Args:
            simulation_axes: List of control net names
            outputs: List of output net names

        Returns:
            dict: Coupling test result from equivalence_checker.independence_detector
        """
        # Filter out ground
        ground_nets = {'net:0', 'net:gnd', 'net:GND'}
        sweepable_axes = [net for net in simulation_axes if net not in ground_nets]

        if len(sweepable_axes) < 2:
            return {
                'coupled': False,
                'sources': sweepable_axes,
                'coupling_strength': 0.0,
                'recommendation': '1D',
                'test_details': {'reason': 'single_input'}
            }

        # Create runner if not provided
        if self.runner is None:
            from ngspice_runner import NgspiceRunner
            self.runner = NgspiceRunner()

        # Test first two sources
        src1 = sweepable_axes[0].replace("net:", "")
        src2 = sweepable_axes[1].replace("net:", "")
        output = outputs[0].replace("net:", "")

        # Run independence test
        try:
            result = test_source_independence(
                self.netlist,
                src1,
                src2,
                output,
                self.runner,
                vdd=self.vdd,
                coupling_threshold=0.05,  # 5% threshold
                n_test_points=3  # Test at 3 values of src2
            )
            return result
        except Exception as e:
            # If test fails, assume coupling (conservative approach)
            print(f"      ⚠ Independence test failed: {e}")
            print(f"      → Assuming sources are coupled (conservative)")
            return {
                'coupled': True,
                'sources': [src1, src2],
                'coupling_strength': 1.0,
                'recommendation': '2D',
                'test_details': {'error': str(e), 'reason': 'test_failure'}
            }

    def plan_dc_op(self, block):
        """
        Generate DC operating point analysis parameters

        Args:
            block: Block dict from pipeline_ext.circuit_analyzer

        Returns:
            dict: DC OP parameters
        """
        outputs = block.get('outputs', set())
        observe_vars = [n.replace("net:", "") for n in outputs]

        return {
            'type': 'dc_op',
            'observe': observe_vars
        }

    def plan_transient(self, block):
        """
        Generate transient analysis parameters for oscillators and dynamic circuits.

        Args:
            block: Block dict from pipeline_ext.circuit_analyzer with:
                   - simulation_axes: set of control nets (if any)
                   - outputs: set of output nets
                   - behavior_class: str classification
                   - name: block name (used for oscillator detection)

        Returns:
            dict: Transient simulation parameters or None if not applicable
        """
        outputs = block.get('outputs', set())
        block_name = block.get('name', '').lower()

        if not outputs:
            return None

        # Detect if this is an oscillator/VCO circuit
        is_oscillator = self._is_oscillator_block(block)

        if not is_oscillator:
            return None

        # Determine simulation parameters based on expected frequency
        expected_freq = self._estimate_oscillator_frequency(block)

        # Run for at least 10 cycles to capture steady-state
        period = 1.0 / expected_freq if expected_freq > 0 else 1e-6
        tstop = 10 * period
        tstep = period / 100  # 100 points per cycle

        # Convert output nets to node names
        observe_vars = [n.replace("net:", "") for n in outputs]

        return {
            'type': 'transient',
            'tstop': tstop,
            'tstep': tstep,
            'tstart': 5 * period,  # Skip first 5 cycles for settling
            'observe': observe_vars,
            'uic': True,  # Use initial conditions for oscillators
            'expected_freq': expected_freq
        }

    def _is_oscillator_block(self, block):
        """
        Detect if a block is likely an oscillator or VCO.

        Args:
            block: Block dict with name, devices, topology info

        Returns:
            bool: True if likely oscillator
        """
        block_name = block.get('name', '').lower()

        # Name-based detection (most reliable)
        oscillator_keywords = ['osc', 'vco', 'ring', 'pll', 'clock', 'clk']
        if any(keyword in block_name for keyword in oscillator_keywords):
            return True

        # Topology-based detection: ring oscillators have odd number of inverters
        # (This would require more sophisticated graph analysis)

        # No control inputs (simulation_axes) is a strong indicator
        # Oscillators are autonomous - they don't need external signals to run
        simulation_axes = block.get('simulation_axes', set())
        has_signal_inputs = len([ax for ax in simulation_axes
                                if ax.replace("net:", "").lower() not in
                                ['vdd', 'vcc', 'vss', 'gnd', '0']]) > 0

        # If no signal inputs and has outputs, might be oscillator
        outputs = block.get('outputs', set())
        if not has_signal_inputs and len(outputs) > 0:
            # Additional heuristic: oscillators often have feedback
            # (would need more graph analysis to detect)
            return True

        return False

    def _estimate_oscillator_frequency(self, block):
        """
        Estimate the oscillation frequency of a circuit.

        Args:
            block: Block dict

        Returns:
            float: Estimated frequency in Hz (default 1GHz if unknown)
        """
        block_name = block.get('name', '').lower()

        # Try to extract frequency from name (e.g., "vco_1ghz")
        import re
        freq_patterns = [
            (r'(\d+\.?\d*)\s*ghz', 1e9),
            (r'(\d+\.?\d*)\s*mhz', 1e6),
            (r'(\d+\.?\d*)\s*khz', 1e3),
        ]

        for pattern, multiplier in freq_patterns:
            match = re.search(pattern, block_name, re.IGNORECASE)
            if match:
                freq_value = float(match.group(1))
                return freq_value * multiplier

        # Default: assume 1 GHz for high-speed circuits
        # (Conservative - leads to short simulation time)
        return 1e9


# Example usage
if __name__ == "__main__":
    # This would normally come from pipeline_ext.circuit_analyzer.py
    import networkx as nx
    from pipeline_ext.graph_builder import parse_spice_netlist, build_bipartite_graph
    from pipeline_ext.circuit_analyzer import analyze_blocks

    # Example netlist
    spice_netlist = """
    M1 vd vg 0 0 NMOS W=1u L=1u
    VDD vd 0 DC 1.8V
    Vin vg 0 DC 0V
    """

    # Build graph and analyze
    from pipeline_ext.graph_builder import parse_spice_netlist, build_bipartite_graph
    devices = parse_spice_netlist(spice_netlist)
    graph = build_bipartite_graph(devices)

    # Analyze (this would use circuit_analyzer.py)
    from pipeline_ext.circuit_analyzer import analyze_blocks, find_constant_nets
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
