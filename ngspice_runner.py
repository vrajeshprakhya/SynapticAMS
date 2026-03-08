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

    def _find_voltage_source_for_node(self, netlist, node_name):
        """
        Find the voltage or current source device that drives a given node.

        The .DC command requires a SOURCE NAME (e.g. "Vin"), not a node name
        (e.g. "inp"). This helper maps node names to source device names so
        that callers can pass either form.

        Returns:
            str: Source device name (e.g. "Vin", "Isrc") if found,
                 otherwise the original node_name unchanged.
        """
        for line in netlist.split('\n'):
            line = line.strip()
            if not line or line.startswith('*') or line.startswith('.'):
                continue
            if line[0].upper() not in ('V', 'I'):
                continue
            tokens = line.split()
            if len(tokens) < 3:
                continue
            if tokens[1].lower() == node_name.lower():
                return tokens[0]
        return node_name

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

    def dc_sweep_2d(self, netlist, sweep_params):
        """
        Run a 2D nested DC sweep analysis.

        Args:
            netlist: SPICE netlist as string
            sweep_params: Dict with:
                - sweep_var_1: Outer sweep variable (source name or node name)
                - start_1, stop_1, step_1: Outer sweep range/step
                - sweep_var_2: Inner sweep variable (source name or node name)
                - start_2, stop_2, step_2: Inner sweep range/step
                - observe: List of node names to observe

        Returns:
            dict: {
                sweep_var_1: 1D array of unique outer values,
                sweep_var_2: 1D array of unique inner values,
                obs_var:     2D array of shape (n_outer, n_inner),
                ...
            }
        """
        for strategy_idx, strategy in enumerate(self.RETRY_STRATEGIES):
            try:
                return self._run_dc_sweep_2d_once(netlist, sweep_params, strategy)
            except NgspiceError as e:
                if strategy_idx == len(self.RETRY_STRATEGIES) - 1:
                    raise NgspiceError(
                        f"All retry strategies failed. Last error: {e}")

    def _run_dc_sweep_2d_once(self, netlist, sweep_params, strategy):
        deck = self._build_dc_sweep_2d_deck(netlist, sweep_params, strategy)
        output = self._execute_ngspice(deck)
        results = self._parse_dc_sweep_2d_output(
            output,
            sweep_params['sweep_var_1'],
            sweep_params['sweep_var_2'],
            sweep_params['observe'],
        )
        if not results or len(results.get(sweep_params['sweep_var_1'], [])) == 0:
            raise NgspiceError("No data points in 2D simulation output")
        return results

    def _build_dc_sweep_2d_deck(self, netlist, sweep_params, strategy):
        sv1 = sweep_params['sweep_var_1']
        sv2 = sweep_params['sweep_var_2']
        observe = sweep_params['observe']

        # Resolve node names → source device names for the .dc command.
        src1 = self._find_voltage_source_for_node(netlist, sv1)
        src2 = self._find_voltage_source_for_node(netlist, sv2)

        observe_list = [v for v in observe if v not in (sv1, sv2)]
        options_line = (f".options {strategy['options']}\n"
                        if 'options' in strategy else "")

        return f"""* Auto-generated 2D DC sweep deck
{netlist}

{options_line}
.dc {src1} {sweep_params['start_1']} {sweep_params['stop_1']} {sweep_params['step_1']} {src2} {sweep_params['start_2']} {sweep_params['stop_2']} {sweep_params['step_2']}

.control
run
print {sv1} {sv2} {' '.join(observe_list)}
quit
.endc

.end
"""

    def _parse_dc_sweep_2d_output(self, output, sweep_var_1, sweep_var_2,
                                   observe_vars):
        """
        Parse ngspice 2D DC sweep output.

        ngspice splits the run into one table per outer-sweep step.  Each
        table has a header line starting with "Index" followed by a dashes
        separator and then data rows.  Column names are matched against the
        variables we care about (case-insensitive, stripping the "v-" prefix
        that ngspice sometimes prepends).
        """
        all_vars  = [sweep_var_1, sweep_var_2] + list(observe_vars)
        all_data  = {v: [] for v in all_vars}

        lines           = output.split('\n')
        current_header  = None
        in_data_section = False

        for line in lines:
            line = line.strip()
            if not line:
                in_data_section = False
                continue

            if line.startswith('Index'):
                current_header  = line.split()
                in_data_section = False
                continue

            if line.startswith('---'):
                in_data_section = True
                continue

            if in_data_section and current_header:
                tokens = line.split()
                if len(tokens) < 2:
                    continue
                try:
                    values = [float(t) for t in tokens[1:]]   # skip index
                    for i, col in enumerate(current_header[1:]):
                        if i >= len(values):
                            break
                        norm_col = col.lower().lstrip('v').lstrip('-')
                        for var in all_vars:
                            if (norm_col == var.lower()
                                    or col.lower() == var.lower()):
                                all_data[var].append(values[i])
                                break
                except (ValueError, IndexError):
                    continue

        import numpy as np
        sv1_arr = np.array(all_data[sweep_var_1])
        sv2_arr = np.array(all_data[sweep_var_2])

        if len(sv1_arr) == 0 or len(sv2_arr) == 0:
            return {}

        unique_1 = np.unique(sv1_arr)
        unique_2 = np.unique(sv2_arr)
        n1, n2   = len(unique_1), len(unique_2)

        results = {sweep_var_1: unique_1, sweep_var_2: unique_2}
        for var in observe_vars:
            flat = np.array(all_data[var])
            results[var] = flat.reshape((n1, n2)) if len(flat) == n1 * n2 else flat

        return results

    def ac_sweep(self, netlist, ac_params):
        """
        Run an AC frequency sweep analysis (.AC).

        Args:
            netlist: SPICE netlist (DC bias already set, AC source declared)
            ac_params: Dict with:
                - sweep_type:   'dec' | 'oct' | 'lin'  (default 'dec')
                - n_points:     points per decade/octave, or total for 'lin'
                                (default 10)
                - start_freq:   start frequency in Hz (default 1)
                - stop_freq:    stop frequency in Hz  (default 1e9)
                - input_node:   node driven by the AC source (default 'vin')
                - output_nodes: list of nodes to measure
                - ac_magnitude: AC source magnitude     (default 1.0)

        Returns:
            dict: {
                'frequency': np.array,
                node_name: {
                    'magnitude_db': np.array,
                    'magnitude':    np.array (linear),
                    'phase':        np.array (degrees)
                }, ...
            }
        """
        deck   = self._build_ac_sweep_deck(netlist, ac_params)
        output = self._execute_ngspice(deck)
        return self._parse_ac_sweep_output(output, ac_params.get('output_nodes', []))

    def _build_ac_sweep_deck(self, netlist, ac_params):
        sweep_type   = ac_params.get('sweep_type', 'dec')
        n_points     = ac_params.get('n_points', 10)
        start_freq   = ac_params.get('start_freq', 1)
        stop_freq    = ac_params.get('stop_freq', 1e9)
        input_node   = ac_params.get('input_node', 'vin')
        output_nodes = ac_params.get('output_nodes', [])
        ac_mag       = ac_params.get('ac_magnitude', 1.0)

        # Add AC specification to the V source driving input_node if not
        # already present in the netlist.
        if f'ac {ac_mag}' not in netlist.lower():
            modified = []
            for ln in netlist.split('\n'):
                if (input_node.lower() in ln.lower()
                        and ln.strip() and ln.strip()[0].upper() == 'V'):
                    ln = ln.rstrip() + (
                        f' AC {ac_mag}' if 'dc' in ln.lower()
                        else f' DC 0 AC {ac_mag}')
                modified.append(ln)
            netlist = '\n'.join(modified)

        observe_list = []
        for node in output_nodes:
            nc = node.replace('net:', '')
            observe_list += [f'vdb({nc})', f'vp({nc})']

        return f"""* Auto-generated AC sweep deck
{netlist}

.ac {sweep_type} {n_points} {start_freq} {stop_freq}

.control
run
print frequency {' '.join(observe_list)}
quit
.endc

.end
"""

    def _parse_ac_sweep_output(self, output, output_nodes):
        """
        Parse ngspice AC sweep output.

        Returns dict keyed by node name (without 'net:' prefix); each value
        is a sub-dict with 'magnitude_db', 'magnitude', and 'phase' arrays,
        plus a top-level 'frequency' array.
        """
        import numpy as np
        results = {'frequency': []}
        for node in output_nodes:
            nc = node.replace('net:', '')
            results[nc] = {'magnitude_db': [], 'magnitude': [], 'phase': []}

        lines           = output.split('\n')
        in_data_section = False

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith('---'):
                in_data_section = True
                continue
            if not in_data_section:
                continue

            tokens = line.split()
            if len(tokens) < 3:
                continue
            try:
                values = [float(t) for t in tokens[1:]]
                if not values:
                    continue
                results['frequency'].append(values[0])
                for i, node in enumerate(output_nodes):
                    nc = node.replace('net:', '')
                    base = i * 2 + 1
                    if base + 1 < len(values):
                        mag_db = values[base]
                        phase  = values[base + 1]
                        results[nc]['magnitude_db'].append(mag_db)
                        results[nc]['magnitude'].append(10 ** (mag_db / 20))
                        results[nc]['phase'].append(phase)
            except (ValueError, IndexError):
                continue

        results['frequency'] = np.array(results['frequency'])
        for node in output_nodes:
            nc = node.replace('net:', '')
            for key in ('magnitude_db', 'magnitude', 'phase'):
                results[nc][key] = np.array(results[nc][key])

        return results

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
