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

    def dc_sweep_2d(self, netlist, sweep_params):
        """
        Run 2D DC sweep analysis (nested sweep)

        Args:
            netlist: SPICE netlist as string (without .end)
            sweep_params: Dict with:
                - sweep_var_1: First variable to sweep (outer loop)
                - start_1, stop_1, step_1: First sweep parameters
                - sweep_var_2: Second variable to sweep (inner loop)
                - start_2, stop_2, step_2: Second sweep parameters
                - observe: List of variables to observe

        Returns:
            dict: {
                sweep_var_1: 1D array of first sweep values,
                sweep_var_2: 1D array of second sweep values,
                'var_name': 2D array of shape (n_sweep1, n_sweep2),
                ...
            }
        """
        # Try with retry strategies
        for strategy_idx, strategy in enumerate(self.RETRY_STRATEGIES):
            try:
                result = self._run_dc_sweep_2d_once(netlist, sweep_params, strategy)
                return result
            except NgspiceError as e:
                if strategy_idx == len(self.RETRY_STRATEGIES) - 1:
                    # Last strategy failed, give up
                    raise NgspiceError(f"All retry strategies failed. Last error: {e}")
                # Try next strategy
                continue

    def _run_dc_sweep_2d_once(self, netlist, sweep_params, strategy):
        """
        Run 2D DC sweep once with given strategy

        Args:
            netlist: SPICE netlist
            sweep_params: 2D sweep parameters
            strategy: Dict with optional 'options' key

        Returns:
            dict: Parsed results with 2D arrays
        """
        # Build complete SPICE deck
        deck = self._build_dc_sweep_2d_deck(netlist, sweep_params, strategy)

        # Execute ngspice
        output = self._execute_ngspice(deck)

        # Parse output
        results = self._parse_dc_sweep_2d_output(
            output,
            sweep_params['sweep_var_1'],
            sweep_params['sweep_var_2'],
            sweep_params['observe']
        )

        # Validate results
        if not results or len(results[sweep_params['sweep_var_1']]) == 0:
            raise NgspiceError("No data points in 2D simulation output")

        return results

    def _build_dc_sweep_2d_deck(self, netlist, sweep_params, strategy):
        """
        Build SPICE deck for 2D DC sweep

        Args:
            netlist: SPICE netlist
            sweep_params: 2D sweep parameters
            strategy: Convergence strategy

        Returns:
            str: Complete SPICE deck
        """
        sweep_var_1 = sweep_params['sweep_var_1']
        start_1 = sweep_params['start_1']
        stop_1 = sweep_params['stop_1']
        step_1 = sweep_params['step_1']

        sweep_var_2 = sweep_params['sweep_var_2']
        start_2 = sweep_params['start_2']
        stop_2 = sweep_params['stop_2']
        step_2 = sweep_params['step_2']

        observe = sweep_params['observe']

        # Map node names to source names
        sweep_source_1 = self._find_voltage_source_for_node(netlist, sweep_var_1)
        sweep_source_2 = self._find_voltage_source_for_node(netlist, sweep_var_2)

        # Build observe list
        observe_list = [sweep_var_1, sweep_var_2] + [v for v in observe if v not in [sweep_var_1, sweep_var_2]]

        # Build options line
        options_line = ""
        if 'options' in strategy:
            options_line = f".options {strategy['options']}\n"

        # Build complete deck with nested DC sweep
        deck = f"""* Auto-generated 2D DC sweep deck
{netlist}

{options_line}
.dc {sweep_source_1} {start_1} {stop_1} {step_1} {sweep_source_2} {start_2} {stop_2} {step_2}

.control
run
print {' '.join(observe_list)}
quit
.endc

.end
"""
        return deck

    def _parse_dc_sweep_2d_output(self, output, sweep_var_1, sweep_var_2, observe_vars):
        """
        Parse ngspice 2D DC sweep output

        2D sweep output format:
            Index   var1            var2            vout
            -------------------------------------------------------
                0   0.000000e+00    0.000000e+00    1.800000e+00
                1   0.000000e+00    1.000000e-01    1.750000e+00
                2   0.000000e+00    2.000000e-01    1.700000e+00
                ...
               10   1.000000e-01    0.000000e+00    1.600000e+00
               11   1.000000e-01    1.000000e-01    1.550000e+00

        Args:
            output: ngspice stdout
            sweep_var_1: Outer sweep variable name
            sweep_var_2: Inner sweep variable name
            observe_vars: List of output variables

        Returns:
            dict: {
                sweep_var_1: 1D array,
                sweep_var_2: 1D array,
                'var_name': 2D array (n_sweep1 × n_sweep2)
            }
        """
        # Parse all tables, matching columns by name
        # ngspice splits output into multiple tables and reorders variables
        all_data = {}  # var_name -> list of values
        all_vars = [sweep_var_1, sweep_var_2] + observe_vars

        for var in all_vars:
            all_data[var] = []

        lines = output.split('\n')
        current_header = None
        in_data_section = False

        for line in lines:
            line = line.strip()

            if not line:
                in_data_section = False  # Reset on empty line
                continue

            # Detect header line (starts with "Index")
            if line.startswith('Index'):
                # Parse header to get column names
                current_header = line.split()
                in_data_section = False
                continue

            # Detect separator line
            if line.startswith('---'):
                in_data_section = True
                continue

            # Parse data lines
            if in_data_section and current_header is not None:
                tokens = line.split()

                if len(tokens) < 2:  # Need at least index + one value
                    continue

                try:
                    # Skip first token (index)
                    values = [float(t) for t in tokens[1:]]

                    # Match columns by name (skip "Index" column)
                    for i, col_name in enumerate(current_header[1:]):  # Skip "Index"
                        if i < len(values):
                            # Normalize column name (remove v- prefix, convert to lowercase)
                            normalized_col = col_name.lower().replace('v-', '')

                            # Check if this column matches any variable we're looking for
                            for var in all_vars:
                                if normalized_col == var.lower() or col_name.lower() == var.lower():
                                    all_data[var].append(values[i])
                                    break

                except (ValueError, IndexError) as e:
                    continue

        # Build results from collected data
        sweep_1_vals = np.array(all_data[sweep_var_1]) if all_data[sweep_var_1] else np.array([])
        sweep_2_vals = np.array(all_data[sweep_var_2]) if all_data[sweep_var_2] else np.array([])

        if len(sweep_1_vals) == 0 or len(sweep_2_vals) == 0:
            # No sweep data found
            return {}

        # Determine grid dimensions
        unique_1 = np.unique(sweep_1_vals)
        unique_2 = np.unique(sweep_2_vals)

        n1 = len(unique_1)
        n2 = len(unique_2)

        # Build results
        results = {
            sweep_var_1: unique_1,
            sweep_var_2: unique_2
        }

        for obs_var in observe_vars:
            data_flat = np.array(all_data[obs_var])
            if len(data_flat) == n1 * n2:
                # Reshape to 2D grid
                results[obs_var] = data_flat.reshape((n1, n2))
            else:
                # Couldn't reshape - return as 1D (or empty)
                results[obs_var] = data_flat

        return results

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
        # IMPORTANT: Filter sweep_var from observe list to match what was printed
        sweep_var = sweep_params['sweep_var']
        observe_filtered = [v for v in sweep_params['observe'] if v != sweep_var]

        results = self._parse_dc_sweep_output(
            output,
            sweep_var,
            observe_filtered
        )

        # Validate results
        if not results or len(results[sweep_params['sweep_var']]) == 0:
            raise NgspiceError("No data points in simulation output")

        return results

    def _find_voltage_source_for_node(self, netlist, node_name):
        """
        Find the voltage or current source that drives a given node

        Args:
            netlist: SPICE netlist as string
            node_name: Node name to search for (e.g., "inp")

        Returns:
            str: Source name (e.g., "Vin" or "Iin") or node_name if not found
        """
        for line in netlist.split('\n'):
            line = line.strip()

            # Skip comments and control lines
            if not line or line.startswith('*') or line.startswith('.'):
                continue

            # Check if this is a voltage or current source (starts with V, v, I, or i)
            if not line[0].upper() in ['V', 'I']:
                continue

            # Parse source line: Sourcename node1 node2 ...
            tokens = re.split(r'\s+', line)
            if len(tokens) < 3:
                continue

            source_name = tokens[0]
            pos_node = tokens[1]  # Positive terminal
            neg_node = tokens[2]  # Negative terminal (usually 0)

            # Check if this source drives the target node
            if pos_node.lower() == node_name.lower():
                return source_name

        # If no source found, return original node name (may fail, but at least try)
        return node_name

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

        # IMPORTANT FIX: Map node name to voltage source name
        # .dc command requires a SOURCE name (e.g., "Vin"), not a node name (e.g., "inp")
        sweep_source = self._find_voltage_source_for_node(netlist, sweep_var)

        # Build observe list
        # Filter out the sweep variable from observe list to avoid duplicates
        # (ngspice prints v-sweep column which is the sweep variable)
        observe_only = [v for v in observe if v != sweep_var]
        # Final list: sweep var + other observables
        observe_list = [sweep_var] + observe_only

        # Build options line
        options_line = ""
        if 'options' in strategy:
            options_line = f".options {strategy['options']}\n"

        # Build complete deck
        deck = f"""* Auto-generated DC sweep deck
{netlist}

{options_line}
.dc {sweep_source} {start} {stop} {step}

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

                if len(tokens) < 3:  # Need at least: index, sweep, one observe
                    continue

                try:
                    # Skip first token (index), get remaining numbers
                    values = [float(t) for t in tokens[1:]]

                    # ngspice outputs: v-sweep, actual_var_name, observe_vars...
                    # v-sweep and actual_var_name are same, so skip first duplicate
                    if len(values) >= 2 and abs(values[0] - values[1]) < 1e-12:
                        # Detected duplicate, skip v-sweep column
                        sweep_val = values[1]
                        observe_vals = values[2:]
                    else:
                        # No duplicate (shouldn't happen but handle it)
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

                # Skip first value (index)
                # Find first unique value (skip duplicates of sweep var)
                data_values = values[1:]

                # Remove consecutive duplicates (v-sweep and actual sweep var)
                unique_values = []
                prev_val = None
                for val in data_values:
                    if prev_val is None or abs(val - prev_val) > 1e-12:
                        unique_values.append(val)
                    prev_val = val

                if len(unique_values) < 1 + len(observe_vars):
                    continue

                # First unique value is sweep variable
                results[sweep_var].append(unique_values[0])

                # Remaining are observe variables
                for i, obs_var in enumerate(observe_vars):
                    if i + 1 < len(unique_values):
                        results[obs_var].append(unique_values[i + 1])

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

    def ac_sweep(self, netlist, ac_params):
        """
        Run AC frequency sweep analysis

        Args:
            netlist: SPICE netlist with DC bias already set
            ac_params: Dict with:
                - sweep_type: 'dec' (decade), 'oct' (octave), or 'lin' (linear)
                - n_points: Number of points per decade/octave (for dec/oct) or total (for lin)
                - start_freq: Start frequency in Hz
                - stop_freq: Stop frequency in Hz
                - input_node: Input node for AC source
                - output_nodes: List of output nodes to measure
                - ac_magnitude: AC source magnitude (default: 1.0)

        Returns:
            dict: {
                'frequency': numpy_array,
                'output_node': {
                    'magnitude': numpy_array,
                    'phase': numpy_array (in degrees)
                }
            }
        """
        # Build complete SPICE deck
        deck = self._build_ac_sweep_deck(netlist, ac_params)

        # Execute ngspice
        output = self._execute_ngspice(deck)

        # Parse output
        results = self._parse_ac_sweep_output(output, ac_params['output_nodes'])

        return results

    def _build_ac_sweep_deck(self, netlist, ac_params):
        """
        Build complete SPICE deck for AC sweep

        Args:
            netlist: Base netlist
            ac_params: AC sweep parameters

        Returns:
            str: Complete SPICE deck
        """
        sweep_type = ac_params.get('sweep_type', 'dec')
        n_points = ac_params.get('n_points', 10)
        start_freq = ac_params.get('start_freq', 1)
        stop_freq = ac_params.get('stop_freq', 1e9)
        input_node = ac_params.get('input_node', 'vin')
        output_nodes = ac_params.get('output_nodes', [])
        ac_mag = ac_params.get('ac_magnitude', 1.0)

        # Add AC source if not already present
        # Check if netlist already has AC source for input_node
        if f'ac {ac_mag}' not in netlist.lower():
            # Add AC source declaration to existing voltage source
            netlist_lines = netlist.split('\n')
            modified_netlist = []
            for line in netlist_lines:
                # Look for voltage source on input_node
                if input_node in line.lower() and line.strip().startswith('v'):
                    # Add AC spec to voltage source
                    if 'dc' in line.lower():
                        line = line.rstrip() + f' AC {ac_mag}'
                    else:
                        line = line.rstrip() + f' DC 0 AC {ac_mag}'
                modified_netlist.append(line)
            netlist = '\n'.join(modified_netlist)

        # Build observe list
        observe_list = []
        for node in output_nodes:
            node_clean = node.replace('net:', '')
            observe_list.append(f'vdb({node_clean})')  # Magnitude in dB
            observe_list.append(f'vp({node_clean})')   # Phase in degrees

        # Build complete deck
        deck = f"""* Auto-generated AC sweep deck
{netlist}

.ac {sweep_type} {n_points} {start_freq} {stop_freq}

.control
run
print frequency {' '.join(observe_list)}
quit
.endc

.end
"""
        return deck

    def _parse_ac_sweep_output(self, output, output_nodes):
        """
        Parse ngspice AC sweep output

        ngspice print format for AC:
            Index   frequency       vdb(vout)       vp(vout)
            -------------------------------------------------------
                0   1.000000e+00    -3.010300e+01   0.000000e+00
                1   1.000000e+01    -2.000000e+01   -4.500000e+01

        Args:
            output: ngspice stdout
            output_nodes: List of output nodes

        Returns:
            dict: {
                'frequency': numpy_array,
                'node_name': {
                    'magnitude_db': numpy_array,
                    'magnitude': numpy_array (linear),
                    'phase': numpy_array (degrees)
                }
            }
        """
        results = {
            'frequency': []
        }

        for node in output_nodes:
            node_clean = node.replace('net:', '')
            results[node_clean] = {
                'magnitude_db': [],
                'magnitude': [],
                'phase': []
            }

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
                tokens = line.split()

                if len(tokens) < 3:  # Need at least: index, frequency, one measurement
                    continue

                try:
                    # Skip first token (index), get remaining numbers
                    values = [float(t) for t in tokens[1:]]

                    if len(values) < 1:
                        continue

                    # First value is frequency
                    freq = values[0]
                    results['frequency'].append(freq)

                    # Remaining values are magnitude_db, phase pairs for each output
                    mag_phase_values = values[1:]

                    for i, node in enumerate(output_nodes):
                        node_clean = node.replace('net:', '')

                        # Each output has 2 values: magnitude_db and phase
                        if i * 2 + 1 < len(mag_phase_values):
                            mag_db = mag_phase_values[i * 2]
                            phase = mag_phase_values[i * 2 + 1]

                            results[node_clean]['magnitude_db'].append(mag_db)
                            results[node_clean]['magnitude'].append(10 ** (mag_db / 20))  # Convert dB to linear
                            results[node_clean]['phase'].append(phase)

                except (ValueError, IndexError):
                    continue

        # Convert to numpy arrays
        results['frequency'] = np.array(results['frequency'])
        for node in output_nodes:
            node_clean = node.replace('net:', '')
            results[node_clean]['magnitude_db'] = np.array(results[node_clean]['magnitude_db'])
            results[node_clean]['magnitude'] = np.array(results[node_clean]['magnitude'])
            results[node_clean]['phase'] = np.array(results[node_clean]['phase'])

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
