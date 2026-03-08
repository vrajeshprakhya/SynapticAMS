#!/usr/bin/env python3
"""
equivalence_checker.py

Validates that generated Verilog-AMS behavioral models are equivalent
to the original SPICE netlist within acceptable tolerances.

Strategy:
1. Generate test vectors covering the operating range
2. Simulate SPICE netlist with test vectors
3. Simulate Verilog-AMS model with same test vectors
4. Compare outputs using error metrics
5. Report pass/fail with detailed diagnostics
"""

import numpy as np
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Tuple
import json
from datetime import datetime


@dataclass
class EquivalenceResult:
    """Results of equivalence check"""
    passed: bool
    max_absolute_error: float
    max_relative_error: float
    rms_error: float
    correlation: float
    failing_points: List[Dict]
    coverage_percentage: float

    def __str__(self):
        status = "✓ PASS" if self.passed else "✗ FAIL"
        return f"""
{status} Equivalence Check
{'='*60}
Max Absolute Error: {self.max_absolute_error:.6e}
Max Relative Error: {self.max_relative_error:.2%}
RMS Error:          {self.rms_error:.6e}
Correlation:        {self.correlation:.6f}
Coverage:           {self.coverage_percentage:.1f}%
Failing Points:     {len(self.failing_points)}
{'='*60}
"""


class EquivalenceChecker:
    """
    Checks equivalence between SPICE netlist and Verilog-AMS model

    Uses OpenVAF to compile Verilog-A to OSDI and ngspice to simulate both
    the original SPICE netlist and the compiled OSDI model.
    """

    def __init__(self,
                 abs_tol=1e-3,      # 1mV for voltages, 1uA for currents
                 rel_tol=0.05,       # 5% relative error
                 correlation_threshold=0.98,
                 openvaf_bin='openvaf',
                 ngspice_bin='ngspice',
                 testbench_output_dir=None):
        """
        Args:
            abs_tol: Maximum absolute error threshold
            rel_tol: Maximum relative error threshold (as fraction)
            correlation_threshold: Minimum correlation coefficient
            openvaf_bin: Path to OpenVAF compiler binary
            ngspice_bin: Path to ngspice binary
            testbench_output_dir: Directory to save generated testbenches (None = don't save)
        """
        self.abs_tol = abs_tol
        self.rel_tol = rel_tol
        self.correlation_threshold = correlation_threshold
        self.openvaf_bin = openvaf_bin
        self.ngspice_bin = ngspice_bin
        self.testbench_output_dir = Path(testbench_output_dir) if testbench_output_dir else None

    def check_block_equivalence(self,
                                spice_netlist: str,
                                verilog_ams_code: str,
                                block_info: Dict,
                                test_strategy: str = 'grid') -> EquivalenceResult:
        """
        Check equivalence for a single block

        Args:
            spice_netlist: Original SPICE netlist
            verilog_ams_code: Generated Verilog-AMS module code
            block_info: Block metadata from circuit_analyzer
            test_strategy: 'grid', 'random', or 'adaptive'

        Returns:
            EquivalenceResult with detailed metrics
        """
        # Filter out ground from simulation axes
        block_info_filtered = block_info.copy()
        simulation_axes = set(block_info['simulation_axes'])
        # Remove ground nodes (net:0, 0, GND, gnd, etc.)
        ground_nodes = {'net:0', '0', 'net:gnd', 'gnd', 'net:GND', 'GND'}
        simulation_axes = simulation_axes - ground_nodes
        block_info_filtered['simulation_axes'] = simulation_axes

        if not simulation_axes:
            # No non-ground inputs to sweep
            return EquivalenceResult(
                passed=False,
                max_absolute_error=0.0,
                max_relative_error=0.0,
                rms_error=0.0,
                correlation=0.0,
                failing_points=[],
                coverage_percentage=0.0
            )

        # Step 1: Generate test vectors (pass netlist for source type detection)
        test_vectors = self._generate_test_vectors(block_info_filtered, strategy=test_strategy,
                                                   netlist=spice_netlist)

        # Step 2: Compile Verilog-AMS to OSDI (if testbench saving enabled)
        osdi_file = None
        if self.testbench_output_dir or True:  # Always compile for simulation
            try:
                module_name = self._extract_module_name(verilog_ams_code)
                osdi_file = self._compile_to_osdi(verilog_ams_code, module_name)
            except Exception as e:
                print(f"Warning: OpenVAF compilation failed: {e}")

        # Step 3: Simulate SPICE
        spice_results = self._simulate_spice(spice_netlist, test_vectors, block_info_filtered)

        # Step 4: Simulate Verilog-AMS
        vams_results = self._simulate_verilog_ams_with_osdi(osdi_file, test_vectors, block_info_filtered)

        # Step 5: Save testbenches (if enabled)
        if self.testbench_output_dir:
            block_name = block_info_filtered.get('name', 'unnamed_block')
            self._save_testbenches(block_name, test_vectors, spice_netlist,
                                  verilog_ams_code, block_info_filtered, osdi_file)

        # Step 6: Compare results
        equivalence = self._compare_results(spice_results, vams_results, test_vectors)

        return equivalence

    def _generate_test_vectors(self, block_info: Dict, strategy: str = 'grid',
                              netlist: str = '') -> np.ndarray:
        """
        Generate test input vectors covering the operating range

        Strategies:
        - 'grid': Regular grid sampling (good for 1D/2D)
        - 'random': Monte Carlo sampling (good for 3D+)
        - 'adaptive': Focus on high-curvature regions
        - 'corners': Operating corners + edges
        """
        inputs = list(block_info['simulation_axes'])
        behavior_class = block_info.get('behavior_class', 'NONLINEAR')

        # Detect source types for each input
        source_types = self._detect_source_types(netlist, inputs)

        # Extract VDD from netlist
        vdd = self._extract_vdd_from_netlist(netlist)

        if strategy == 'grid':
            return self._generate_grid_vectors(inputs, behavior_class, source_types,
                                              netlist=netlist, vdd=vdd)
        elif strategy == 'random':
            return self._generate_random_vectors(inputs, behavior_class, source_types,
                                                netlist=netlist, vdd=vdd)
        elif strategy == 'adaptive':
            return self._generate_adaptive_vectors(inputs, behavior_class, source_types,
                                                  netlist=netlist, vdd=vdd)
        elif strategy == 'corners':
            return self._generate_corner_vectors(inputs, behavior_class, source_types,
                                                netlist=netlist, vdd=vdd)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

    def _generate_grid_vectors(self, inputs: List[str], behavior_class: str,
                               source_types: List[str] = None, netlist: str = '',
                               vdd: float = 1.8) -> np.ndarray:
        """
        Regular grid sampling

        Number of points depends on behavior class:
        - STRUCTURAL_LINEAR: Fewer points (20)
        - SMALL_SIGNAL_LINEARIZABLE: Moderate (30)
        - NONLINEAR: More points (50)

        Args:
            inputs: List of input node names
            behavior_class: Circuit behavior classification
            source_types: List of source types ('V' or 'I') for each input
        """
        if behavior_class == 'STRUCTURAL_LINEAR':
            n_points = 20
        elif behavior_class == 'SMALL_SIGNAL_LINEARIZABLE':
            n_points = 30
        else:  # NONLINEAR
            n_points = 50

        # Default to voltage if not specified
        if source_types is None:
            source_types = ['V'] * len(inputs)

        if len(inputs) == 1:
            # 1D sweep
            s_min, s_max = self._get_source_range(source_types[0], vdd=vdd, netlist=netlist)
            return np.linspace(s_min, s_max, n_points).reshape(-1, 1)

        elif len(inputs) == 2:
            # 2D grid
            s1_min, s1_max = self._get_source_range(source_types[0], vdd=vdd, netlist=netlist)
            s2_min, s2_max = self._get_source_range(source_types[1], vdd=vdd, netlist=netlist)

            s1 = np.linspace(s1_min, s1_max, n_points)
            s2 = np.linspace(s2_min, s2_max, n_points)
            S1, S2 = np.meshgrid(s1, s2)
            return np.column_stack([S1.ravel(), S2.ravel()])

        else:
            # 3D+: Use random sampling instead
            return self._generate_random_vectors(inputs, behavior_class, source_types, netlist=netlist, n_samples=1000)

    def _generate_random_vectors(self, inputs: List[str], behavior_class: str,
                                source_types: List[str] = None, netlist: str = '',
                                vdd: float = 1.8, n_samples=1000) -> np.ndarray:
        """
        Monte Carlo random sampling for high-dimensional input spaces

        Uses Latin Hypercube Sampling for better coverage than pure random
        """
        n_inputs = len(inputs)

        # Default to voltage if not specified
        if source_types is None:
            source_types = ['V'] * n_inputs

        # Use Latin Hypercube Sampling for better coverage
        from scipy.stats import qmc
        sampler = qmc.LatinHypercube(d=n_inputs)
        samples = sampler.random(n=n_samples)  # Returns values in [0, 1]

        # Scale each dimension to its appropriate range
        vectors = np.zeros_like(samples)
        for i, stype in enumerate(source_types):
            s_min, s_max = self._get_source_range(stype, vdd=vdd, netlist=netlist)
            vectors[:, i] = s_min + (s_max - s_min) * samples[:, i]

        return vectors

    def _generate_corner_vectors(self, inputs: List[str], behavior_class: str,
                                 source_types: List[str] = None, netlist: str = '',
                                 vdd: float = 1.8) -> np.ndarray:
        """
        Test operating corners and edges

        For 2 inputs: [min,min], [min,max], [max,min], [max,max], [mid,mid]
        Plus edges and interior
        """
        n_inputs = len(inputs)

        # Default to voltage if not specified
        if source_types is None:
            source_types = ['V'] * n_inputs

        # Get min/mid/max for each input
        mins = []
        mids = []
        maxs = []
        for stype in source_types:
            s_min, s_max = self._get_source_range(stype, vdd=vdd, netlist=netlist)
            mins.append(s_min)
            maxs.append(s_max)
            mids.append((s_min + s_max) / 2)

        # Corners (all combinations of min/max)
        from itertools import product
        corners = []
        for combination in product(*zip(mins, maxs)):
            corners.append(combination)

        # Add midpoint
        corners.append(tuple(mids))

        # Add edge centers (one mid, rest min/max)
        for i in range(n_inputs):
            ranges = [zip(mins[j:j+1], maxs[j:j+1]) if j != i else [mids[i]]
                     for j in range(n_inputs)]
            for vals in product(*ranges):
                corners.append(vals)

        return np.array(corners)

    def _generate_adaptive_vectors(self, inputs: List[str], behavior_class: str,
                                  source_types: List[str] = None, netlist: str = '',
                                  vdd: float = 1.8) -> np.ndarray:
        """
        Adaptive sampling: more points where curvature is high

        Algorithm:
        1. Start with coarse grid
        2. Simulate and find high-error regions
        3. Refine grid in those regions
        4. Repeat
        """
        # TODO: Implement adaptive refinement
        # For now, fall back to grid
        return self._generate_grid_vectors(inputs, behavior_class, source_types, netlist=netlist, vdd=vdd)

    def _simulate_spice(self, netlist: str, test_vectors: np.ndarray, block_info: Dict) -> Dict[str, np.ndarray]:
        """
        Simulate SPICE netlist with test vectors using DC sweep (much faster!)

        Returns:
            dict: {output_name: array_of_values}
        """
        from ngspice_runner import NgspiceRunner

        runner = NgspiceRunner()
        inputs = list(block_info['simulation_axes'])
        outputs = list(block_info['outputs'])

        # Clean output names (remove 'net:' prefix) for ngspice
        outputs_clean = [out.replace('net:', '') for out in outputs]

        # Use DC sweep instead of individual DC OP for each vector
        # This is 10-100× faster!
        if len(inputs) == 1:
            # 1D sweep
            sweep_params = {
                'sweep_var': inputs[0],
                'start': test_vectors[0, 0],
                'stop': test_vectors[-1, 0],
                'step': (test_vectors[-1, 0] - test_vectors[0, 0]) / (len(test_vectors) - 1),
                'observe': outputs_clean
            }
            try:
                results = runner.dc_sweep(netlist, sweep_params)
                # Convert to expected format (with 'net:' prefix)
                return {f"net:{out}" if not out.startswith('net:') else out: results[out]
                        for out in outputs_clean}
            except Exception as e:
                print(f"Warning: DC sweep failed: {e}")
                # Fall back to point-by-point
                return self._simulate_spice_point_by_point(netlist, test_vectors, block_info)

        elif len(inputs) == 2:
            # 2D nested sweep
            # Determine sweep parameters from test_vectors grid
            inp1_vals = np.unique(test_vectors[:, 0])
            inp2_vals = np.unique(test_vectors[:, 1])

            sweep_params = {
                'sweep_var_1': inputs[0],
                'start_1': inp1_vals[0],
                'stop_1': inp1_vals[-1],
                'step_1': (inp1_vals[-1] - inp1_vals[0]) / (len(inp1_vals) - 1) if len(inp1_vals) > 1 else 0.1,
                'sweep_var_2': inputs[1],
                'start_2': inp2_vals[0],
                'stop_2': inp2_vals[-1],
                'step_2': (inp2_vals[-1] - inp2_vals[0]) / (len(inp2_vals) - 1) if len(inp2_vals) > 1 else 0.1,
                'observe': outputs_clean
            }
            try:
                results_2d = runner.dc_sweep_2d(netlist, sweep_params)
                # Flatten 2D results to match test_vectors order
                results = {}
                for out in outputs_clean:
                    if out in results_2d:
                        # Flatten 2D array to 1D (row-major order)
                        results[out] = results_2d[out].ravel()
                    else:
                        results[out] = np.full(len(test_vectors), np.nan)
                # Convert to expected format
                return {f"net:{out}" if not out.startswith('net:') else out: results[out]
                        for out in outputs_clean}
            except Exception as e:
                print(f"Warning: 2D DC sweep failed: {e}")
                # Fall back to point-by-point
                return self._simulate_spice_point_by_point(netlist, test_vectors, block_info)

        else:
            # 3D+: No native DC sweep, use point-by-point
            return self._simulate_spice_point_by_point(netlist, test_vectors, block_info)

    def _simulate_spice_point_by_point(self, netlist: str, test_vectors: np.ndarray, block_info: Dict) -> Dict[str, np.ndarray]:
        """
        Fallback: Simulate SPICE point-by-point (slower but works for any dimension)

        Returns:
            dict: {output_name: array_of_values}
        """
        from ngspice_runner import NgspiceRunner

        runner = NgspiceRunner()
        inputs = list(block_info['simulation_axes'])
        outputs = list(block_info['outputs'])

        results = {out: [] for out in outputs}

        # Clean output names (remove 'net:' prefix) for ngspice
        outputs_clean = [out.replace('net:', '') for out in outputs]

        # For each test vector, run DC operating point
        for vector in test_vectors:
            # Build modified netlist with input voltages set
            modified_netlist = self._inject_test_vector(netlist, inputs, vector)

            # Run DC OP with cleaned output names
            try:
                dc_result = runner.dc_op(modified_netlist, outputs_clean)

                for out, out_clean in zip(outputs, outputs_clean):
                    results[out].append(dc_result.get(out_clean, np.nan))

            except Exception as e:
                # Simulation failed - record NaN
                for out in outputs:
                    results[out].append(np.nan)

        # Convert to numpy arrays
        return {k: np.array(v) for k, v in results.items()}

    def _simulate_verilog_ams_with_osdi(self, osdi_file: Path, test_vectors: np.ndarray, block_info: Dict) -> Dict[str, np.ndarray]:
        """
        Simulate Verilog-AMS model using precompiled OSDI file with DC sweep optimization

        Args:
            osdi_file: Path to compiled OSDI file
            test_vectors: Test input vectors
            block_info: Block metadata

        Returns:
            dict: {output_name: array_of_values}
        """
        outputs = list(block_info['outputs'])
        inputs = list(block_info['simulation_axes'])

        if osdi_file is None or not osdi_file.exists():
            print("Warning: OSDI file not available, returning NaN")
            return {out: np.full(len(test_vectors), np.nan) for out in outputs}

        # Extract module name from OSDI file name
        module_name = osdi_file.stem

        # Use DC sweep for 1D and 2D (much faster!)
        if len(inputs) == 1:
            # 1D sweep
            try:
                netlist = self._build_osdi_dc_sweep_testbench(
                    osdi_file, module_name, inputs, outputs, test_vectors, dim=1
                )
                output_text = self._run_ngspice(netlist)
                # Parse DC sweep output
                results = self._parse_dc_sweep_output(output_text, inputs, outputs, test_vectors)
                return results
            except Exception as e:
                print(f"Warning: OSDI DC sweep failed: {e}, falling back to point-by-point")
                return self._simulate_verilog_ams_point_by_point(osdi_file, test_vectors, block_info)

        elif len(inputs) == 2:
            # 2D sweep
            try:
                netlist = self._build_osdi_dc_sweep_testbench(
                    osdi_file, module_name, inputs, outputs, test_vectors, dim=2
                )
                output_text = self._run_ngspice(netlist)
                # Parse DC sweep output
                results = self._parse_dc_sweep_output(output_text, inputs, outputs, test_vectors)
                return results
            except Exception as e:
                print(f"Warning: OSDI 2D DC sweep failed: {e}, falling back to point-by-point")
                return self._simulate_verilog_ams_point_by_point(osdi_file, test_vectors, block_info)

        else:
            # 3D+: No native DC sweep support
            return self._simulate_verilog_ams_point_by_point(osdi_file, test_vectors, block_info)

    def _simulate_verilog_ams_point_by_point(self, osdi_file: Path, test_vectors: np.ndarray, block_info: Dict) -> Dict[str, np.ndarray]:
        """
        Fallback: Simulate OSDI model point-by-point (slower but works for any dimension)

        Returns:
            dict: {output_name: array_of_values}
        """
        outputs = list(block_info['outputs'])
        inputs = list(block_info['simulation_axes'])
        module_name = osdi_file.stem

        # Simulate at each test vector
        results = {out: [] for out in outputs}

        for vector in test_vectors:
            # Build testbench netlist for this test point
            netlist = self._build_osdi_testbench(osdi_file, module_name, inputs, outputs, vector)

            # Run ngspice
            try:
                output_text = self._run_ngspice(netlist)
                dc_vals = self._parse_dc_op(output_text, [out.replace('net:', '') for out in outputs])

                for out in outputs:
                    out_clean = out.replace('net:', '')
                    results[out].append(dc_vals.get(out_clean, np.nan))

            except Exception as e:
                # Simulation failed - record NaN
                for out in outputs:
                    results[out].append(np.nan)

        # Convert to numpy arrays
        return {k: np.array(v) for k, v in results.items()}

    def _simulate_verilog_ams(self, verilog_code: str, test_vectors: np.ndarray, block_info: Dict) -> Dict[str, np.ndarray]:
        """
        Simulate Verilog-AMS model with test vectors using OpenVAF + ngspice OSDI

        Workflow:
        1. Compile Verilog-A to OSDI using OpenVAF
        2. For each test vector, create ngspice netlist with OSDI model
        3. Simulate and extract output values
        4. Return results

        Returns:
            dict: {output_name: array_of_values}
        """
        outputs = list(block_info['outputs'])
        inputs = list(block_info['simulation_axes'])

        # Extract module name from Verilog-A code
        module_name = self._extract_module_name(verilog_code)

        # Step 1: Compile Verilog-A to OSDI
        try:
            osdi_file = self._compile_to_osdi(verilog_code, module_name)
        except Exception as e:
            print(f"Warning: OpenVAF compilation failed: {e}")
            print("Returning NaN for all outputs")
            return {out: np.full(len(test_vectors), np.nan) for out in outputs}

        # Step 2: Simulate at each test vector
        results = {out: [] for out in outputs}

        for vector in test_vectors:
            # Build testbench netlist for this test point
            netlist = self._build_osdi_testbench(osdi_file, module_name, inputs, outputs, vector)

            # Run ngspice
            try:
                output_text = self._run_ngspice(netlist)
                dc_vals = self._parse_dc_op(output_text, [out.replace('net:', '') for out in outputs])

                for out in outputs:
                    out_clean = out.replace('net:', '')
                    results[out].append(dc_vals.get(out_clean, np.nan))
            except Exception as e:
                # Simulation failed - record NaN
                for out in outputs:
                    results[out].append(np.nan)

        return {k: np.array(v) for k, v in results.items()}

    def _detect_source_types(self, netlist: str, inputs: List[str]) -> List[str]:
        """
        Detect whether each input is driven by voltage (V) or current (I) source

        Args:
            netlist: SPICE netlist as string
            inputs: List of input node names (e.g., ['net:vin', 'net:ibias'])

        Returns:
            List of source types ('V' or 'I') corresponding to each input
        """
        import re

        source_types = []

        for inp in inputs:
            inp_clean = inp.replace('net:', '')
            source_type = 'V'  # Default to voltage

            # Search for sources connected to this node
            for line in netlist.split('\n'):
                line = line.strip()

                # Skip comments and control lines
                if not line or line.startswith('*') or line.startswith('.'):
                    continue

                # Check if this is a source line (V or I)
                if not line[0].upper() in ['V', 'I']:
                    continue

                # Parse source line: Sourcename node1 node2 DC value
                tokens = re.split(r'\s+', line)
                if len(tokens) < 3:
                    continue

                source_name = tokens[0]
                pos_node = tokens[1]  # Positive terminal

                # Check if this source drives the target node
                if pos_node.lower() == inp_clean.lower():
                    source_type = source_name[0].upper()  # 'V' or 'I'
                    break

            source_types.append(source_type)

        return source_types

    def _extract_all_supplies_from_netlist(self, netlist: str) -> Dict[str, float]:
        """
        Extract ALL supply voltages from netlist

        Finds all voltage sources and categorizes them as power supplies
        (both positive and negative).

        Args:
            netlist: SPICE netlist as string

        Returns:
            dict: {net_name: voltage_value} for all supplies
                  Example: {'vdd': 3.3, 'vss': -3.3, 'vddio': 1.8}
        """
        import re

        supplies = {}

        for line in netlist.split('\n'):
            line = line.strip()

            # Skip comments and control lines
            if not line or line.startswith('*') or line.startswith('.'):
                continue

            # Look for voltage sources: Vxxx node1 node2 DC <value>
            if not line[0].upper() == 'V':
                continue

            # Parse: VDD vdd 0 DC 1.8V
            tokens = re.split(r'\s+', line)
            if len(tokens) < 4:
                continue

            source_name = tokens[0]
            pos_node = tokens[1].lower()
            neg_node = tokens[2].lower()

            # Extract DC value
            match = re.search(r'DC\s+([-+]?[\d.eE+-]+)\s*[Vv]?', line, re.IGNORECASE)
            if match:
                voltage = float(match.group(1))

                # Filter out ground and small signal sources
                # Keep power supplies (|V| > 0.5V)
                if abs(voltage) > 0.5:
                    # Store by the non-ground node name
                    if neg_node in ['0', 'gnd', 'ground']:
                        supplies[pos_node] = voltage
                    elif pos_node in ['0', 'gnd', 'ground']:
                        supplies[neg_node] = voltage
                    else:
                        # Both nodes are non-ground (differential supply?)
                        supplies[pos_node] = voltage

        return supplies

    def _extract_vdd_from_netlist(self, netlist: str) -> float:
        """
        Extract VDD (supply voltage) from netlist

        For single-supply circuits: returns that supply
        For multi-supply circuits: returns maximum positive supply

        Args:
            netlist: SPICE netlist as string

        Returns:
            Supply voltage in Volts (default 1.8V if not found)
        """
        supplies = self._extract_all_supplies_from_netlist(netlist)

        if not supplies:
            return 1.8  # Default

        # Get all positive supplies
        positive_supplies = {k: v for k, v in supplies.items() if v > 0}

        if not positive_supplies:
            return 1.8  # No positive supplies found

        # Return maximum positive supply
        max_supply = max(positive_supplies.values())

        # If multiple supplies detected, could log a warning here
        if len(positive_supplies) > 1:
            # Multiple voltage domains - using conservative max
            pass

        return max_supply

    def _extract_all_currents_from_netlist(self, netlist: str) -> Dict[str, float]:
        """
        Extract ALL current sources from netlist

        Finds all current sources and their DC values.
        Handles units: A, mA, uA/µA, nA

        Args:
            netlist: SPICE netlist as string

        Returns:
            dict: {net_name: current_value} for all current sources
                  Example: {'ibias1': 100e-6, 'ibias2': 10e-6, 'iref': 1e-3}
        """
        import re

        currents = {}

        for line in netlist.split('\n'):
            line = line.strip()

            # Skip comments and control lines
            if not line or line.startswith('*') or line.startswith('.'):
                continue

            # Look for current sources: Ixxx node1 node2 DC <value>
            if not line[0].upper() == 'I':
                continue

            # Parse: Ibias bias 0 DC 50uA
            tokens = re.split(r'\s+', line)
            if len(tokens) < 4:
                continue

            source_name = tokens[0]
            pos_node = tokens[1].lower()
            neg_node = tokens[2].lower()

            # Extract DC value
            # Pattern matches: DC <number><unit>
            match = re.search(r'DC\s+([\d.eE+-]+)\s*([uµnmkKMG]?)[Aa]?', line, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                unit = match.group(2) if len(match.groups()) > 1 and match.group(2) else ''

                # Convert to Amps based on unit
                if unit.lower() in ['u', 'µ']:
                    value *= 1e-6  # microamps
                elif unit.lower() == 'n':
                    value *= 1e-9  # nanoamps
                elif unit.lower() == 'm':
                    value *= 1e-3  # milliamps
                elif unit.lower() == 'k':
                    value *= 1e3   # kiloamps
                elif unit.lower() in ['meg', 'g']:
                    value *= 1e6   # megaamps
                # else: already in Amps

                # Filter out very small currents (< 1nA)
                if abs(value) > 1e-9:
                    # Store by the non-ground node name
                    if neg_node in ['0', 'gnd', 'ground']:
                        currents[pos_node] = abs(value)
                    elif pos_node in ['0', 'gnd', 'ground']:
                        currents[neg_node] = abs(value)
                    else:
                        # Both nodes are non-ground
                        currents[pos_node] = abs(value)

        return currents

    def _extract_max_current_from_netlist(self, netlist: str) -> float:
        """
        Extract maximum current source value from netlist

        For multi-current circuits: returns maximum current value

        Args:
            netlist: SPICE netlist as string

        Returns:
            Maximum current in Amps (default 100µA if no current sources found)
        """
        currents = self._extract_all_currents_from_netlist(netlist)

        if not currents:
            return 100e-6  # Default: 100µA

        # Return maximum current
        max_current = max(currents.values())

        # If multiple current sources detected, could log a warning here
        if len(currents) > 1:
            # Multiple current sources - using conservative max
            pass

        return max_current

    def _get_source_range(self, source_type: str, vdd: float = 1.8,
                          netlist: str = '') -> Tuple[float, float]:
        """
        Get appropriate sweep range based on source type

        Args:
            source_type: 'V' for voltage or 'I' for current
            vdd: Supply voltage (for voltage sources)
            netlist: SPICE netlist (for extracting current ranges)

        Returns:
            (min, max) tuple for the source
        """
        if source_type == 'V':
            # Voltage source: 0 to VDD
            return (0.0, vdd)
        else:  # 'I'
            # Current source: extract from netlist with 2× safety margin
            max_current = self._extract_max_current_from_netlist(netlist)
            return (0.0, max_current * 2.0)  # 2× margin for safety

    def _extract_module_name(self, verilog_code: str) -> str:
        """
        Extract module name from Verilog-A code

        Looks for: module <name>(...)

        Returns:
            Module name, or 'generated_module' if not found
        """
        import re
        match = re.search(r'module\s+(\w+)\s*\(', verilog_code)
        if match:
            return match.group(1)
        else:
            return 'generated_module'

    def _compile_to_osdi(self, verilog_code: str, module_name: str) -> Path:
        """
        Compile Verilog-A to OSDI binary using OpenVAF

        Args:
            verilog_code: Verilog-A source code
            module_name: Name of the module

        Returns:
            Path to compiled .osdi file

        Raises:
            RuntimeError: If compilation fails
        """
        temp_dir = Path(tempfile.mkdtemp())
        va_file = temp_dir / f"{module_name}.va"
        osdi_file = temp_dir / f"{module_name}.osdi"

        # Write Verilog-A code to file
        with open(va_file, 'w') as f:
            f.write(verilog_code)

        # Compile with OpenVAF
        result = subprocess.run(
            [self.openvaf_bin, str(va_file), '-o', str(osdi_file)],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0 or not osdi_file.exists():
            raise RuntimeError(f"OpenVAF compilation failed:\n{result.stderr}")

        return osdi_file

    def _build_osdi_testbench(self, osdi_file: Path, module_name: str,
                              input_names: List[str], output_names: List[str],
                              input_vector: np.ndarray) -> str:
        """
        Build ngspice netlist to simulate OSDI model at a specific test point

        Creates a testbench that:
        1. Loads the OSDI model with pre_osdi
        2. Sets up voltage/current sources for inputs
        3. Instantiates the OSDI device
        4. Runs DC operating point analysis
        """
        # Clean node names (remove 'net:' prefix)
        inputs_clean = [name.replace('net:', '') for name in input_names]
        outputs_clean = [name.replace('net:', '') for name in output_names]

        # Build sources for inputs (voltage or current based on value magnitude)
        sources = []
        for i, (name, val) in enumerate(zip(inputs_clean, input_vector)):
            # Heuristic: values < 1mA are likely currents, otherwise voltages
            if val < 1e-3:
                sources.append(f"Iin{i} {name} 0 DC {val:.12e}A")
            else:
                sources.append(f"Vin{i} {name} 0 DC {val:.12e}V")

        # Build node list for OSDI device (outputs first, then inputs)
        all_nodes = outputs_clean + inputs_clean
        node_str = ' '.join(all_nodes)

        netlist = f"""* OSDI testbench for {module_name}

.model osdi_model {module_name}

{chr(10).join(sources)}

* OSDI device: N<name> <nodes...> <model_name>
Nmodel {node_str} osdi_model

.control
pre_osdi {osdi_file}
op
print {' '.join(outputs_clean)}
quit
.endc

.end
"""
        return netlist

    def _run_ngspice(self, netlist: str) -> str:
        """
        Execute ngspice in batch mode with the given netlist

        Returns:
            stdout from ngspice containing simulation results
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            f.write(netlist)
            cir_file = f.name

        try:
            result = subprocess.run(
                [self.ngspice_bin, '-b', cir_file],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout
        finally:
            Path(cir_file).unlink(missing_ok=True)

    def _parse_dc_op(self, output: str, var_names: List[str]) -> Dict[str, float]:
        """
        Parse DC operating point output from ngspice

        Looks for lines like:
            var_name = 1.234e-03

        Args:
            output: ngspice stdout text
            var_names: list of variable names to extract

        Returns:
            dict mapping variable names to their values
        """
        import re
        results = {}

        for var in var_names:
            # Match: var_name = value (including scientific notation)
            pattern = rf'{re.escape(var)}\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)'
            match = re.search(pattern, output, re.MULTILINE)
            if match:
                results[var] = float(match.group(1))

        return results

    def _build_osdi_dc_sweep_testbench(self, osdi_file: Path, module_name: str,
                                        inputs: List[str], outputs: List[str],
                                        test_vectors: np.ndarray, dim: int) -> str:
        """
        Build OSDI testbench with DC sweep (much faster than point-by-point!)

        Args:
            osdi_file: Path to compiled OSDI file
            module_name: Module name
            inputs: List of input names
            outputs: List of output names
            test_vectors: All test vectors
            dim: Dimension (1 or 2)

        Returns:
            Complete ngspice netlist with DC sweep command
        """
        inputs_clean = [inp.replace('net:', '') for inp in inputs]
        outputs_clean = [out.replace('net:', '') for out in outputs]

        # Build voltage sources for inputs
        sources = []
        for i, inp in enumerate(inputs_clean):
            sources.append(f"V{inp} {inp} 0 DC 0")

        # Build OSDI device instantiation
        all_nodes = outputs_clean + inputs_clean
        node_str = ' '.join(all_nodes)

        # Build DC sweep command
        if dim == 1:
            # 1D sweep
            var = inputs_clean[0]
            start = np.min(test_vectors[:, 0])
            stop = np.max(test_vectors[:, 0])
            n_points = len(test_vectors)
            step = (stop - start) / (n_points - 1) if n_points > 1 else 0.1
            dc_command = f"dc V{var} {start} {stop} {step}"

        elif dim == 2:
            # 2D nested sweep
            inp1_vals = np.unique(test_vectors[:, 0])
            inp2_vals = np.unique(test_vectors[:, 1])

            var1 = inputs_clean[0]
            var2 = inputs_clean[1]

            start1 = inp1_vals[0]
            stop1 = inp1_vals[-1]
            step1 = (stop1 - start1) / (len(inp1_vals) - 1) if len(inp1_vals) > 1 else 0.1

            start2 = inp2_vals[0]
            stop2 = inp2_vals[-1]
            step2 = (stop2 - start2) / (len(inp2_vals) - 1) if len(inp2_vals) > 1 else 0.1

            dc_command = f"dc V{var1} {start1} {stop1} {step1} V{var2} {start2} {stop2} {step2}"

        else:
            raise ValueError(f"Unsupported dimension: {dim}")

        # Build complete netlist
        netlist = f"""* OSDI DC Sweep Testbench for {module_name}
* Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
* Sweep: {dim}D grid ({len(test_vectors)} total points)

.model osdi_model {module_name}

{chr(10).join(sources)}

* OSDI device: N<name> <nodes...> <model_name>
Nmodel {node_str} osdi_model

.control
pre_osdi {osdi_file}
{dc_command}
print {' '.join(outputs_clean)}
quit
.endc

.end
"""
        return netlist

    def _parse_dc_sweep_output(self, output: str, inputs: List[str],
                                outputs: List[str], test_vectors: np.ndarray) -> Dict[str, np.ndarray]:
        """
        Parse DC sweep output from ngspice

        This is a simplified parser that uses ngspice_runner's parsing logic.
        For production, should use proper ngspice output parsing.

        Args:
            output: ngspice stdout
            inputs: Input names
            outputs: Output names
            test_vectors: Expected test vectors (for size)

        Returns:
            dict: {output_name: array_of_values}
        """
        # For now, use ngspice_runner's parsing which handles DC sweep properly
        # This is a placeholder - the actual DC sweep will be handled by
        # ngspice_runner.dc_sweep() or dc_sweep_2d() which have proper parsers

        # Return NaN arrays as fallback (actual implementation delegated to ngspice_runner)
        outputs_clean = [out.replace('net:', '') for out in outputs]
        return {out: np.full(len(test_vectors), np.nan) for out in outputs}

    def _inject_test_vector(self, netlist: str, inputs: List[str], vector: np.ndarray) -> str:
        """
        Modify SPICE netlist to set input source values to test values

        Handles both voltage (V) and current (I) sources
        Replaces source values or adds new sources
        """
        import re

        modified = netlist

        for inp, value in zip(inputs, vector):
            inp_clean = inp.replace('net:', '')

            # Try to find and modify voltage source
            v_pattern = rf'(V\w+\s+{inp_clean}\s+\S+\s+DC\s+)[\d.eE+-]+[VvAa]?'
            if re.search(v_pattern, modified, re.IGNORECASE):
                modified = re.sub(v_pattern, rf'\g<1>{value:.12e}V', modified, flags=re.IGNORECASE)
                continue

            # Try to find and modify current source
            i_pattern = rf'(I\w+\s+{inp_clean}\s+\S+\s+DC\s+)[\d.eE+-]+[VvAa]?'
            if re.search(i_pattern, modified, re.IGNORECASE):
                modified = re.sub(i_pattern, rf'\g<1>{value:.12e}A', modified, flags=re.IGNORECASE)
                continue

            # If neither found, detect which type we need and add it
            # Check if value looks like current (< 1mA) or voltage
            if value < 1e-3:
                # Likely current source
                modified += f"\nItest_{inp_clean} {inp_clean} 0 DC {value:.12e}A\n"
            else:
                # Likely voltage source
                modified += f"\nVtest_{inp_clean} {inp_clean} 0 DC {value:.12e}V\n"

        return modified

    def _compare_results(self,
                        spice_results: Dict[str, np.ndarray],
                        vams_results: Dict[str, np.ndarray],
                        test_vectors: np.ndarray) -> EquivalenceResult:
        """
        Compare SPICE vs Verilog-AMS results using multiple metrics

        Metrics:
        1. Maximum absolute error: max|y_spice - y_vams|
        2. Maximum relative error: max|(y_spice - y_vams)/y_spice|
        3. RMS error: sqrt(mean((y_spice - y_vams)^2))
        4. Correlation coefficient: corr(y_spice, y_vams)
        5. Per-point pass/fail based on tolerances
        """
        all_abs_errors = []
        all_rel_errors = []
        failing_points = []

        for output_name in spice_results.keys():
            y_spice = spice_results[output_name]
            y_vams = vams_results.get(output_name, np.full_like(y_spice, np.nan))

            # Remove NaN pairs
            valid_mask = ~(np.isnan(y_spice) | np.isnan(y_vams))
            y_s = y_spice[valid_mask]
            y_v = y_vams[valid_mask]

            if len(y_s) == 0:
                continue

            # Absolute error
            abs_err = np.abs(y_s - y_v)
            all_abs_errors.extend(abs_err)

            # Relative error (avoid division by zero)
            rel_err = np.abs((y_s - y_v) / (np.abs(y_s) + 1e-12))
            all_rel_errors.extend(rel_err)

            # Find failing points
            fails = (abs_err > self.abs_tol) & (rel_err > self.rel_tol)
            for i, is_fail in enumerate(fails):
                if is_fail:
                    failing_points.append({
                        'output': output_name,
                        'inputs': test_vectors[valid_mask][i].tolist(),
                        'spice_value': float(y_s[i]),
                        'vams_value': float(y_v[i]),
                        'abs_error': float(abs_err[i]),
                        'rel_error': float(rel_err[i])
                    })

        # Aggregate metrics
        all_abs_errors = np.array(all_abs_errors)
        all_rel_errors = np.array(all_rel_errors)

        max_abs_error = np.max(all_abs_errors) if len(all_abs_errors) > 0 else 0.0
        max_rel_error = np.max(all_rel_errors) if len(all_rel_errors) > 0 else 0.0
        rms_error = np.sqrt(np.mean(all_abs_errors**2)) if len(all_abs_errors) > 0 else 0.0

        # Correlation (flatten all outputs)
        all_spice = np.concatenate([spice_results[k] for k in spice_results.keys()])
        all_vams = np.concatenate([vams_results.get(k, np.full_like(spice_results[k], np.nan))
                                   for k in spice_results.keys()])
        valid = ~(np.isnan(all_spice) | np.isnan(all_vams))

        if np.sum(valid) > 1:
            correlation = np.corrcoef(all_spice[valid], all_vams[valid])[0, 1]
        else:
            correlation = 0.0

        # Coverage: percentage of test vectors that succeeded
        coverage = 100.0 * np.sum(valid) / len(all_spice) if len(all_spice) > 0 else 0.0

        # Pass criteria:
        # 1. Max errors within tolerance
        # 2. High correlation
        # 3. High coverage
        passed = (
            max_abs_error <= self.abs_tol and
            max_rel_error <= self.rel_tol and
            correlation >= self.correlation_threshold and
            coverage >= 95.0  # At least 95% of points simulated successfully
        )

        return EquivalenceResult(
            passed=passed,
            max_absolute_error=max_abs_error,
            max_relative_error=max_rel_error,
            rms_error=rms_error,
            correlation=correlation,
            failing_points=failing_points[:10],  # Keep first 10 failures
            coverage_percentage=coverage
        )

    def _save_testbenches(self, block_name: str, test_vectors: np.ndarray,
                         spice_netlist: str, verilog_code: str,
                         block_info: Dict, osdi_file: Path = None):
        """
        Save representative testbenches to organized directory structure

        Directory structure:
        testbench_output_dir/
            block_name/
                spice/
                    testbench_000.cir
                    testbench_050.cir
                    ...
                verilog_ams/
                    testbench_000.cir
                    testbench_050.cir
                    ...
                test_manifest.json

        Args:
            block_name: Name of the block being tested
            test_vectors: All test vectors (only subset will be saved)
            spice_netlist: SPICE subcircuit definition
            verilog_code: Verilog-AMS module code
            block_info: Block metadata
            osdi_file: Path to compiled OSDI file (for Verilog-AMS testbenches)
        """
        if not self.testbench_output_dir:
            return  # Testbench saving disabled

        # Create directory structure
        block_dir = self.testbench_output_dir / block_name
        spice_dir = block_dir / 'spice'
        vams_dir = block_dir / 'verilog_ams'

        spice_dir.mkdir(parents=True, exist_ok=True)
        vams_dir.mkdir(parents=True, exist_ok=True)

        # Select representative test vectors to save
        # Save: first 5, middle 5, last 5 (or all if < 20 vectors)
        n_vectors = len(test_vectors)
        if n_vectors <= 20:
            save_indices = list(range(n_vectors))
        else:
            first_5 = list(range(5))
            middle_5 = list(range(n_vectors // 2 - 2, n_vectors // 2 + 3))
            last_5 = list(range(n_vectors - 5, n_vectors))
            save_indices = sorted(set(first_5 + middle_5 + last_5))

        inputs = list(block_info['simulation_axes'])
        outputs = list(block_info['outputs'])
        module_name = self._extract_module_name(verilog_code) if verilog_code else block_name

        # Save testbenches
        saved_testbenches = []
        for idx in save_indices:
            vector = test_vectors[idx]

            # SPICE testbench
            spice_tb = self._build_spice_testbench(spice_netlist, inputs, outputs,
                                                   vector, block_info)
            spice_file = spice_dir / f"testbench_{idx:03d}.cir"
            spice_file.write_text(spice_tb)

            # Verilog-AMS testbench
            if osdi_file and osdi_file.exists():
                vams_tb = self._build_osdi_testbench(osdi_file, module_name,
                                                     inputs, outputs, vector)
                vams_file = vams_dir / f"testbench_{idx:03d}.cir"
                vams_file.write_text(vams_tb)
            else:
                vams_file = None

            saved_testbenches.append({
                'index': idx,
                'inputs': vector.tolist(),
                'spice_testbench': str(spice_file.relative_to(self.testbench_output_dir)),
                'vams_testbench': str(vams_file.relative_to(self.testbench_output_dir)) if vams_file else None
            })

        # Save manifest
        manifest = {
            'block_name': block_name,
            'total_test_vectors': n_vectors,
            'saved_testbenches': len(save_indices),
            'inputs': inputs,
            'outputs': outputs,
            'testbenches': saved_testbenches,
            'generated_at': datetime.now().isoformat()
        }

        # Generate master DC sweep testbenches (MUCH more efficient!)
        if len(inputs) <= 2:  # Only for 1D and 2D (DC sweep supported)
            # SPICE master testbench
            master_spice = self._build_dc_sweep_testbench(
                spice_netlist, inputs, outputs, test_vectors, block_info
            )
            master_spice_file = block_dir / 'master_dc_sweep_spice.cir'
            master_spice_file.write_text(master_spice)
            manifest['master_dc_sweep_spice'] = str(master_spice_file.relative_to(self.testbench_output_dir))

            # Verilog-AMS master testbench
            if osdi_file and osdi_file.exists():
                master_vams = self._build_osdi_dc_sweep_testbench(
                    osdi_file, module_name, inputs, outputs, test_vectors,
                    dim=len(inputs)
                )
                master_vams_file = block_dir / 'master_dc_sweep_verilog_ams.cir'
                master_vams_file.write_text(master_vams)
                manifest['master_dc_sweep_verilog_ams'] = str(master_vams_file.relative_to(self.testbench_output_dir))

        # Save manifest
        manifest_file = block_dir / 'test_manifest.json'
        with open(manifest_file, 'w') as f:
            json.dump(manifest, f, indent=2)

        print(f"  Saved {len(save_indices)} point testbenches + master DC sweep to {block_dir}")

    def _build_spice_testbench(self, spice_netlist: str, inputs: List[str],
                               outputs: List[str], vector: np.ndarray,
                               block_info: Dict) -> str:
        """
        Build complete SPICE testbench with test vector injected

        Returns:
            Complete SPICE netlist ready to simulate
        """
        # Inject test vector into netlist
        modified_netlist = self._inject_test_vector(spice_netlist, inputs, vector)

        # Clean output names
        outputs_clean = [out.replace('net:', '') for out in outputs]

        # Build complete testbench
        testbench = f"""* SPICE Testbench for {block_info.get('name', 'block')}
* Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
* Test vector {list(inputs)}: {vector.tolist()}

{modified_netlist}

.op

.control
run
print {' '.join(outputs_clean)}
quit
.endc

.end
"""
        return testbench

    def _build_dc_sweep_testbench(self, spice_netlist: str, inputs: List[str],
                                   outputs: List[str], test_vectors: np.ndarray,
                                   block_info: Dict) -> str:
        """
        Build master DC sweep testbench (MUCH more efficient than point-by-point!)

        Generates a single testbench that sweeps all inputs using DC analysis.
        This runs 10-100× faster than individual point simulations.

        Returns:
            Complete SPICE netlist with DC sweep command
        """
        outputs_clean = [out.replace('net:', '') for out in outputs]
        inputs_clean = [inp.replace('net:', '') for inp in inputs]

        # Determine sweep parameters from test_vectors
        if len(inputs) == 1:
            # 1D sweep
            sweep_var = inputs_clean[0]
            start = np.min(test_vectors[:, 0])
            stop = np.max(test_vectors[:, 0])
            n_points = len(test_vectors)
            step = (stop - start) / (n_points - 1) if n_points > 1 else 0.1

            dc_command = f".dc V{sweep_var} {start} {stop} {step}"

        elif len(inputs) == 2:
            # 2D nested sweep
            # Extract unique values for each dimension
            inp1_vals = np.unique(test_vectors[:, 0])
            inp2_vals = np.unique(test_vectors[:, 1])

            var1 = inputs_clean[0]
            var2 = inputs_clean[1]

            start1 = inp1_vals[0]
            stop1 = inp1_vals[-1]
            step1 = (stop1 - start1) / (len(inp1_vals) - 1) if len(inp1_vals) > 1 else 0.1

            start2 = inp2_vals[0]
            stop2 = inp2_vals[-1]
            step2 = (stop2 - start2) / (len(inp2_vals) - 1) if len(inp2_vals) > 1 else 0.1

            # Nested DC sweep
            dc_command = f".dc V{var1} {start1} {stop1} {step1} V{var2} {start2} {stop2} {step2}"

        else:
            # 3D+: Not supported by DC sweep
            return "* DC sweep not supported for 3D+ inputs\n"

        # Build testbench
        testbench = f"""* Master DC Sweep Testbench for {block_info.get('name', 'block')}
* Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
* Sweep: {len(inputs)}D grid ({len(test_vectors)} total points)
* MUCH faster than individual point simulations!

{spice_netlist}

* DC sweep command (sweeps all test points in one simulation)
{dc_command}

.control
run
print {' '.join(outputs_clean)}
quit
.endc

.end
"""
        return testbench


def generate_equivalence_report(results: Dict[str, EquivalenceResult], output_file: str):
    """
    Generate HTML report of equivalence checking results

    Args:
        results: Dict mapping block_id to EquivalenceResult
        output_file: Path to output HTML file
    """
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Model Equivalence Report</title>
        <style>
            body {{ font-family: monospace; margin: 20px; }}
            .pass {{ color: green; font-weight: bold; }}
            .fail {{ color: red; font-weight: bold; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <h1>Model-Schematic Equivalence Check Report</h1>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

        <h2>Summary</h2>
        <table>
            <tr>
                <th>Block ID</th>
                <th>Status</th>
                <th>Max Abs Error</th>
                <th>Max Rel Error</th>
                <th>Correlation</th>
                <th>Coverage</th>
            </tr>
    """

    for block_id, result in results.items():
        status_class = "pass" if result.passed else "fail"
        status_text = "PASS" if result.passed else "FAIL"

        html += f"""
            <tr>
                <td>{block_id}</td>
                <td class="{status_class}">{status_text}</td>
                <td>{result.max_absolute_error:.3e}</td>
                <td>{result.max_relative_error:.2%}</td>
                <td>{result.correlation:.4f}</td>
                <td>{result.coverage_percentage:.1f}%</td>
            </tr>
        """

    html += """
        </table>

        <h2>Detailed Results</h2>
    """

    for block_id, result in results.items():
        html += f"<h3>Block {block_id}</h3>"
        html += f"<pre>{result}</pre>"

        if result.failing_points:
            html += "<h4>Sample Failing Points</h4><table>"
            html += "<tr><th>Output</th><th>Inputs</th><th>SPICE</th><th>VAMS</th><th>Error</th></tr>"

            for pt in result.failing_points[:5]:
                html += f"""
                <tr>
                    <td>{pt['output']}</td>
                    <td>{pt['inputs']}</td>
                    <td>{pt['spice_value']:.6f}</td>
                    <td>{pt['vams_value']:.6f}</td>
                    <td>{pt['abs_error']:.6f}</td>
                </tr>
                """
            html += "</table>"

    html += """
    </body>
    </html>
    """

    with open(output_file, 'w') as f:
        f.write(html)


# Example usage
if __name__ == "__main__":
    from graph_builder import parse_spice_netlist, build_bipartite_graph
    from circuit_analyzer import analyze_blocks

    # Test netlist
    spice_netlist = """
* Common source amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

    # Analyze
    devices = parse_spice_netlist(spice_netlist)
    graph = build_bipartite_graph(devices)
    blocks = analyze_blocks(graph)

    # Example Verilog-AMS (simplified)
    verilog_code = """
module vout_vs_vin(output electrical vout, input electrical vin);
    analog begin
        V(vout) <+ 1.8 - 0.5 * (V(vin) - 0.4)**2;
    end
endmodule
"""

    # Check equivalence
    checker = EquivalenceChecker(abs_tol=0.01, rel_tol=0.05)

    result = checker.check_block_equivalence(
        spice_netlist=spice_netlist,
        verilog_ams_code=verilog_code,
        block_info=blocks[0],
        test_strategy='grid'
    )

    print(result)
