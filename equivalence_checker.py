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
    """

    def __init__(self,
                 abs_tol=1e-3,      # 1mV for voltages, 1uA for currents
                 rel_tol=0.05,       # 5% relative error
                 correlation_threshold=0.98):
        """
        Args:
            abs_tol: Maximum absolute error threshold
            rel_tol: Maximum relative error threshold (as fraction)
            correlation_threshold: Minimum correlation coefficient
        """
        self.abs_tol = abs_tol
        self.rel_tol = rel_tol
        self.correlation_threshold = correlation_threshold

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
        # Step 1: Generate test vectors
        test_vectors = self._generate_test_vectors(block_info, strategy=test_strategy)

        # Step 2: Simulate SPICE
        spice_results = self._simulate_spice(spice_netlist, test_vectors, block_info)

        # Step 3: Simulate Verilog-AMS
        vams_results = self._simulate_verilog_ams(verilog_ams_code, test_vectors, block_info)

        # Step 4: Compare results
        equivalence = self._compare_results(spice_results, vams_results, test_vectors)

        return equivalence

    def _generate_test_vectors(self, block_info: Dict, strategy: str = 'grid') -> np.ndarray:
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

        if strategy == 'grid':
            return self._generate_grid_vectors(inputs, behavior_class)
        elif strategy == 'random':
            return self._generate_random_vectors(inputs, behavior_class)
        elif strategy == 'adaptive':
            return self._generate_adaptive_vectors(inputs, behavior_class)
        elif strategy == 'corners':
            return self._generate_corner_vectors(inputs, behavior_class)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

    def _generate_grid_vectors(self, inputs: List[str], behavior_class: str) -> np.ndarray:
        """
        Regular grid sampling

        Number of points depends on behavior class:
        - STRUCTURAL_LINEAR: Fewer points (20)
        - SMALL_SIGNAL_LINEARIZABLE: Moderate (30)
        - NONLINEAR: More points (50)
        """
        if behavior_class == 'STRUCTURAL_LINEAR':
            n_points = 20
        elif behavior_class == 'SMALL_SIGNAL_LINEARIZABLE':
            n_points = 30
        else:  # NONLINEAR
            n_points = 50

        # Assume 0 to 1.8V range (TODO: extract from netlist)
        v_min, v_max = 0.0, 1.8

        if len(inputs) == 1:
            # 1D sweep
            return np.linspace(v_min, v_max, n_points).reshape(-1, 1)

        elif len(inputs) == 2:
            # 2D grid
            v1 = np.linspace(v_min, v_max, n_points)
            v2 = np.linspace(v_min, v_max, n_points)
            V1, V2 = np.meshgrid(v1, v2)
            return np.column_stack([V1.ravel(), V2.ravel()])

        else:
            # 3D+: Use random sampling instead
            return self._generate_random_vectors(inputs, behavior_class)

    def _generate_random_vectors(self, inputs: List[str], behavior_class: str, n_samples=1000) -> np.ndarray:
        """
        Monte Carlo random sampling for high-dimensional input spaces
        """
        v_min, v_max = 0.0, 1.8
        n_inputs = len(inputs)

        # Use Latin Hypercube Sampling for better coverage
        from scipy.stats import qmc
        sampler = qmc.LatinHypercube(d=n_inputs)
        samples = sampler.random(n=n_samples)

        # Scale to voltage range
        vectors = v_min + (v_max - v_min) * samples

        return vectors

    def _generate_corner_vectors(self, inputs: List[str], behavior_class: str) -> np.ndarray:
        """
        Test operating corners and edges

        For 2 inputs: [0,0], [0,1.8], [1.8,0], [1.8,1.8], [0.9,0.9]
        Plus edges and interior
        """
        v_min, v_max = 0.0, 1.8
        v_mid = (v_min + v_max) / 2
        n_inputs = len(inputs)

        # Corners (all combinations of min/max)
        from itertools import product
        corners = list(product([v_min, v_max], repeat=n_inputs))

        # Add midpoint
        corners.append(tuple([v_mid] * n_inputs))

        # Add edge centers (one mid, rest min/max)
        for i in range(n_inputs):
            for vals in product([v_min, v_max], repeat=n_inputs-1):
                point = list(vals[:i]) + [v_mid] + list(vals[i:])
                corners.append(tuple(point))

        return np.array(corners)

    def _generate_adaptive_vectors(self, inputs: List[str], behavior_class: str) -> np.ndarray:
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
        return self._generate_grid_vectors(inputs, behavior_class)

    def _simulate_spice(self, netlist: str, test_vectors: np.ndarray, block_info: Dict) -> Dict[str, np.ndarray]:
        """
        Simulate SPICE netlist with test vectors

        Returns:
            dict: {output_name: array_of_values}
        """
        from ngspice_runner import NgspiceRunner

        runner = NgspiceRunner()
        inputs = list(block_info['simulation_axes'])
        outputs = list(block_info['outputs'])

        results = {out: [] for out in outputs}

        # For each test vector, run DC operating point
        for vector in test_vectors:
            # Build modified netlist with input voltages set
            modified_netlist = self._inject_test_vector(netlist, inputs, vector)

            # Run DC OP
            try:
                dc_result = runner.dc_op(modified_netlist, outputs)

                for out in outputs:
                    out_clean = out.replace('net:', '')
                    results[out].append(dc_result.get(out_clean, np.nan))

            except Exception as e:
                # Simulation failed - record NaN
                for out in outputs:
                    results[out].append(np.nan)

        # Convert to numpy arrays
        return {k: np.array(v) for k, v in results.items()}

    def _simulate_verilog_ams(self, verilog_code: str, test_vectors: np.ndarray, block_info: Dict) -> Dict[str, np.ndarray]:
        """
        Simulate Verilog-AMS model with test vectors

        Uses commercial simulator (Cadence AMS, Synopsys VCS-MX, etc.)
        or open-source (Xyce with ADMS)

        Returns:
            dict: {output_name: array_of_values}
        """
        # TODO: Implement Verilog-AMS simulation
        # This depends on available tools:
        # - Cadence: Use spectre with AMS extension
        # - Synopsys: Use VCS-MX
        # - Open source: Use Xyce with ADMS-compiled modules

        # For now, placeholder that uses direct model evaluation
        return self._evaluate_vams_model_directly(verilog_code, test_vectors, block_info)

    def _evaluate_vams_model_directly(self, verilog_code: str, test_vectors: np.ndarray, block_info: Dict) -> Dict[str, np.ndarray]:
        """
        Direct evaluation by extracting equations from Verilog-AMS

        This is a workaround when no Verilog-AMS simulator is available.
        Parses the generated equations and evaluates them directly.
        """
        # Extract the analog block equations
        # This is fragile but works for our generated code

        outputs = list(block_info['outputs'])
        inputs = list(block_info['simulation_axes'])

        results = {out: [] for out in outputs}

        # Parse equations from Verilog-AMS (simple regex-based parser)
        equations = self._extract_vams_equations(verilog_code)

        for vector in test_vectors:
            # Create variable context
            context = {inp.replace('net:', ''): val for inp, val in zip(inputs, vector)}

            # Evaluate equations
            for out in outputs:
                out_clean = out.replace('net:', '')
                if out_clean in equations:
                    try:
                        value = self._eval_vams_expression(equations[out_clean], context)
                        results[out].append(value)
                    except:
                        results[out].append(np.nan)
                else:
                    results[out].append(np.nan)

        return {k: np.array(v) for k, v in results.items()}

    def _extract_vams_equations(self, verilog_code: str) -> Dict[str, str]:
        """
        Extract output equations from Verilog-AMS code

        Looks for patterns like:
            V(output) <+ expression;
        """
        import re

        equations = {}

        # Pattern: V(output_name) <+ expression;
        pattern = r'V\((\w+)\)\s*<\+\s*([^;]+);'

        for match in re.finditer(pattern, verilog_code):
            output_name = match.group(1)
            expression = match.group(2).strip()
            equations[output_name] = expression

        return equations

    def _eval_vams_expression(self, expr: str, context: Dict[str, float]) -> float:
        """
        Safely evaluate a Verilog-AMS expression

        This is simplified - real implementation needs full Verilog-AMS parser
        """
        import re

        # Replace V(signal) with variable value
        def replace_voltage(match):
            sig = match.group(1)
            return str(context.get(sig, 0.0))

        expr = re.sub(r'V\((\w+)\)', replace_voltage, expr)

        # Add math functions
        eval_context = {
            'tanh': np.tanh,
            'exp': np.exp,
            'log': np.log,
            'sqrt': np.sqrt,
            'pow': np.power,
            **context
        }

        # Evaluate (careful: potential security issue in production)
        try:
            return eval(expr, {"__builtins__": {}}, eval_context)
        except:
            return np.nan

    def _inject_test_vector(self, netlist: str, inputs: List[str], vector: np.ndarray) -> str:
        """
        Modify SPICE netlist to set input voltages to test values

        Replaces voltage source values or adds new sources
        """
        import re

        modified = netlist

        for inp, value in zip(inputs, vector):
            inp_clean = inp.replace('net:', '')

            # Pattern: Vin vin 0 DC 0V
            # Replace with: Vin vin 0 DC {value}V
            pattern = rf'(V{inp_clean}\s+{inp_clean}\s+\S+\s+DC\s+)[\d.]+V?'
            replacement = rf'\g<1>{value:.6f}V'

            if re.search(pattern, modified, re.IGNORECASE):
                modified = re.sub(pattern, replacement, modified, flags=re.IGNORECASE)
            else:
                # Add new voltage source if not found
                modified += f"\nV{inp_clean} {inp_clean} 0 DC {value:.6f}V\n"

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
