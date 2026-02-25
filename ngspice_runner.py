#!/usr/bin/env python3
"""
ngspice_runner.py

Executes ngspice simulations and parses results into numpy arrays.

Handles:
- DC sweep analysis
- DC operating point analysis
- Convergence error recovery with retry strategies
- Output parsing from ngspice text format
"""

import subprocess
import tempfile
import re
import numpy as np
from pathlib import Path


class NgspiceError(Exception):
    """Exception raised when ngspice simulation fails"""
    pass


class NgspiceRunner:
    """
    Executes ngspice simulations and parses results
    """

    # Retry strategies for convergence failures
    RETRY_STRATEGIES = [
        # Strategy 0: Default settings
        {},

        # Strategy 1: Tighter tolerances
        {'options': 'reltol=1e-5 abstol=1e-13'},

        # Strategy 2: Gmin stepping
        {'options': 'gmin=1e-11 rshunt=1e12'},

        # Strategy 3: Different integration method
        {'options': 'method=gear'},

        # Strategy 4: Source stepping (for DC)
        {'options': 'srcsteps=10'},
    ]

    def __init__(self, ngspice_bin='ngspice', timeout=60):
        """
        Args:
            ngspice_bin: Path to ngspice executable
            timeout: Simulation timeout in seconds
        """
        self.ngspice_bin = ngspice_bin
        self.timeout = timeout

    def dc_sweep(self, netlist, sweep_params):
        """
        Run DC sweep analysis

        Args:
            netlist: SPICE netlist as string (without .end)
            sweep_params: Dict with:
                - sweep_var: Variable to sweep (e.g., "Vin")
                - start: Start value
                - stop: Stop value
                - step: Step size
                - observe: List of variables to observe

        Returns:
            dict: {var_name: numpy_array, ...}
                 e.g., {'Vin': array([0, 0.1, 0.2, ...]),
                        'vd': array([1.8, 1.75, 1.7, ...])}
        """
        # Try with retry strategies
        for strategy_idx, strategy in enumerate(self.RETRY_STRATEGIES):
            try:
                result = self._run_dc_sweep_once(netlist, sweep_params, strategy)
                return result
            except NgspiceError as e:
                if strategy_idx == len(self.RETRY_STRATEGIES) - 1:
                    # Last strategy failed, give up
                    raise NgspiceError(f"All retry strategies failed. Last error: {e}")
                # Try next strategy
                continue

    def _run_dc_sweep_once(self, netlist, sweep_params, strategy):
        """
        Run DC sweep once with given strategy

        Args:
            netlist: SPICE netlist
            sweep_params: Sweep parameters
            strategy: Dict with optional 'options' key

        Returns:
            dict: Parsed results
        """
        # Build complete SPICE deck
        deck = self._build_dc_sweep_deck(netlist, sweep_params, strategy)

        # Execute ngspice
        output = self._execute_ngspice(deck)

        # Parse output
        results = self._parse_dc_sweep_output(
            output,
            sweep_params['sweep_var'],
            sweep_params['observe']
        )

        # Validate results
        if not results or len(results[sweep_params['sweep_var']]) == 0:
            raise NgspiceError("No data points in simulation output")

        return results

    def _build_dc_sweep_deck(self, netlist, sweep_params, strategy):
        """
        Build complete SPICE deck for DC sweep

        Args:
            netlist: Base netlist
            sweep_params: Sweep parameters
            strategy: Options strategy

        Returns:
            str: Complete SPICE deck
        """
        sweep_var = sweep_params['sweep_var']
        start = sweep_params['start']
        stop = sweep_params['stop']
        step = sweep_params['step']
        observe = sweep_params['observe']

        # Only print the observe variables — ngspice always outputs v-sweep as the
        # x-axis column regardless, so printing the sweep source name (e.g. "Vin")
        # causes a "vector not available" warning and breaks the output.
        observe_list = [v for v in observe if v != sweep_var]

        # Build options line
        options_line = ""
        if 'options' in strategy:
            options_line = f".options {strategy['options']}\n"

        # Build complete deck
        deck = f"""* Auto-generated DC sweep deck
{netlist}

{options_line}
.dc {sweep_var} {start} {stop} {step}

.control
run
print {' '.join(observe_list)}
quit
.endc

.end
"""
        return deck

    def dc_op(self, netlist, observe_vars):
        """
        Run DC operating point analysis

        Args:
            netlist: SPICE netlist
            observe_vars: List of variables to observe

        Returns:
            dict: {var_name: value, ...}
        """
        # Build complete SPICE deck
        deck = f"""* Auto-generated DC OP deck
{netlist}

.op

.control
run
print {' '.join(observe_vars)}
quit
.endc

.end
"""

        # Execute ngspice
        output = self._execute_ngspice(deck)

        # Parse DC OP output (single point)
        results = self._parse_dc_op_output(output, observe_vars)

        return results

    def _execute_ngspice(self, deck):
        """
        Execute ngspice with given deck

        Args:
            deck: Complete SPICE deck as string

        Returns:
            str: ngspice stdout output

        Raises:
            NgspiceError: If execution fails
        """
        # Write deck to temporary file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.cir',
            delete=False
        ) as f:
            f.write(deck)
            deck_file = f.name

        try:
            # Run ngspice in batch mode
            result = subprocess.run(
                [self.ngspice_bin, '-b', deck_file],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            # Check for errors
            if result.returncode != 0:
                raise NgspiceError(
                    f"ngspice exited with code {result.returncode}\n"
                    f"stderr: {result.stderr}"
                )

            # Check for convergence errors
            if 'convergence' in result.stderr.lower():
                raise NgspiceError(f"Convergence failure: {result.stderr}")

            return result.stdout

        except subprocess.TimeoutExpired:
            raise NgspiceError(f"Simulation timeout after {self.timeout}s")

        finally:
            # Clean up temporary file
            Path(deck_file).unlink(missing_ok=True)

    def _parse_dc_sweep_output(self, output, sweep_var, observe_vars):
        """
        Parse ngspice DC sweep output

        ngspice print format:
            Index   v-sweep         vin             vout
            -------------------------------------------------------
                0   0.000000e+00    0.000000e+00    1.800000e+00
                1   3.600000e-01    3.600000e-01    1.800000e+00

        Note: v-sweep and actual sweep var (e.g., vin) are duplicates!

        Args:
            output: ngspice stdout
            sweep_var: Name of sweep variable
            observe_vars: List of variables to observe

        Returns:
            dict: {var_name: numpy_array}
        """
        results = {sweep_var: [], **{v: [] for v in observe_vars}}

        lines = output.split('\n')
        in_data_section = False

        for line in lines:
            line = line.strip()

            if not line:
                continue

            # Detect separator line
            if line.startswith('---'):
                in_data_section = True
                continue

            # Parse data lines (after separator)
            if in_data_section:
                # Try to parse as tab or space-separated numbers
                tokens = line.split()

                if len(tokens) < 3:  # Need at least: index, v-sweep, one observe
                    continue

                try:
                    # Skip first token (index), get remaining numbers.
                    # ngspice always outputs v-sweep as the first column; we no
                    # longer print the sweep source name, so there is no duplicate.
                    values = [float(t) for t in tokens[1:]]
                    sweep_val = values[0]
                    observe_vals = values[1:]

                    results[sweep_var].append(sweep_val)

                    for i, obs_var in enumerate(observe_vars):
                        if i < len(observe_vals):
                            results[obs_var].append(observe_vals[i])

                except (ValueError, IndexError):
                    continue

        # Convert to numpy arrays
        results = {k: np.array(v) for k, v in results.items()}

        # Validate
        if len(results[sweep_var]) == 0:
            # Try alternative method
            results = self._parse_dc_sweep_output_alternative(
                output, sweep_var, observe_vars
            )

        return results

    def _parse_dc_sweep_output_alternative(self, output, sweep_var, observe_vars):
        """
        Alternative parser for different ngspice output formats

        ngspice outputs: Index, v-sweep, <sweep_var_name>, <observe_vars...>
        where v-sweep and sweep_var_name are duplicates!
        """
        results = {sweep_var: [], **{v: [] for v in observe_vars}}

        # Look for lines with scientific notation numbers
        lines = output.split('\n')

        for line in lines:
            # Match lines with multiple scientific notation numbers
            # e.g., "0       0.000000e+00    0.000000e+00    1.800000e+00"
            scientific_pattern = r'[-+]?\d*\.?\d+[eE][-+]?\d+'
            matches = re.findall(scientific_pattern, line)

            # Need at least: index + sweep (possibly duplicated) + observe vars
            if len(matches) < 2:
                continue

            try:
                values = [float(m) for m in matches]

                # The integer row index (0, 1, 2, ...) doesn't match the
                # scientific-notation regex, so `values` already contains only
                # [v-sweep, obs1, obs2, ...].  No column to skip.
                if len(values) < 1 + len(observe_vars):
                    continue

                results[sweep_var].append(values[0])

                for i, obs_var in enumerate(observe_vars):
                    results[obs_var].append(values[i + 1])

            except (ValueError, IndexError):
                continue

        # Convert to numpy arrays
        results = {k: np.array(v) for k, v in results.items()}

        return results

    def _parse_dc_op_output(self, output, observe_vars):
        """
        Parse DC operating point output

        Args:
            output: ngspice stdout
            observe_vars: List of variables

        Returns:
            dict: {var_name: value}
        """
        results = {}

        # Look for variable = value patterns
        for var in observe_vars:
            # Pattern: var_name = value
            pattern = rf'{re.escape(var)}\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)'
            match = re.search(pattern, output, re.IGNORECASE)

            if match:
                results[var] = float(match.group(1))
            else:
                results[var] = None

        return results

    def extract_ac_params(self, netlist, device_names):
        """
        Extract small-signal AC parameters (gm, gds, gmb) from devices

        Args:
            netlist: SPICE netlist with DC bias set
            device_names: List of device names to analyze (e.g., ["M1", "M2"])

        Returns:
            dict: {device_name: {'gm': value, 'gds': value, 'gmb': value}}
        """
        # Build show commands for all devices
        show_commands = '\n'.join([f"show {dev}" for dev in device_names])

        # Build complete SPICE deck
        deck = f"""* Auto-generated AC parameter extraction
{netlist}

.op

.control
run
{show_commands}
quit
.endc

.end
"""

        # Execute ngspice
        output = self._execute_ngspice(deck)

        # Parse AC parameters from show output for each device
        results = {}
        for device_name in device_names:
            params = self._parse_ac_params_output(output, device_name)
            results[device_name] = params

        return results

    def _parse_ac_params_output(self, output, device_name):
        """
        Parse gm, gds, gmb from ngspice 'show' output for a specific device

        Example output:
            device                    m1
              model                  nmos
                 gm             6.216e-05
                gds               3.6e-07
                gmb                     0

        Args:
            output: ngspice stdout from 'show' command
            device_name: Device to extract params for

        Returns:
            dict: {'gm': value, 'gds': value, 'gmb': value}
        """
        results = {'gm': 0.0, 'gds': 0.0, 'gmb': 0.0}

        lines = output.split('\n')

        # Find the section for this device
        in_device_section = False

        for line in lines:
            line_stripped = line.strip()

            # Check if we're entering the device section
            if 'device' in line_stripped and device_name.lower() in line_stripped.lower():
                in_device_section = True
                continue

            # Exit device section when we hit another device or empty model section
            if in_device_section and line_stripped.startswith('device') and device_name.lower() not in line_stripped.lower():
                break

            # Parse parameters within device section
            if in_device_section:
                for param in ['gm', 'gds', 'gmb']:
                    if line_stripped.startswith(param):
                        tokens = line_stripped.split()
                        if len(tokens) >= 2:
                            try:
                                results[param] = float(tokens[1])
                            except ValueError:
                                pass

        return results


# Example usage
if __name__ == "__main__":
    # Example: Run DC sweep on simple NMOS circuit
    netlist = """
M1 vd vg 0 0 NMOS W=1u L=1u
VDD vd 0 DC 1.8V
Vin vg 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

    sweep_params = {
        'sweep_var': 'Vin',
        'start': 0.0,
        'stop': 1.8,
        'step': 0.1,
        'observe': ['vd', 'vg']
    }

    runner = NgspiceRunner()

    try:
        print("Running DC sweep...")
        results = runner.dc_sweep(netlist, sweep_params)

        print("\nResults:")
        for var, values in results.items():
            print(f"{var}: {len(values)} points")
            print(f"  Range: [{values.min():.3f}, {values.max():.3f}]")
            print(f"  First 5: {values[:5]}")

    except NgspiceError as e:
        print(f"Simulation failed: {e}")
