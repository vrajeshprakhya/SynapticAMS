#!/usr/bin/env python3
"""
ngspice_runner.py

Executes ngspice simulations and parses results into numpy arrays.

Handles:
- DC sweep analysis (1D and 2D nested)
- AC small-signal sweep analysis
- DC operating point analysis
- Convergence error recovery with retry strategies
- Output parsing from ngspice text format

ngspice manual references (v45):
- .DC syntax:    §11.3.2  — srcnam vstart vstop vincr [src2 ...]
- .AC syntax:    §11.3.1  — dec/oct/lin n fstart fstop
- .OP syntax:    §11.3.5
- .options:      §11.1    — RELTOL/ABSTOL/GMIN/RSHUNT/SRCSTEPS/ITL1/ITL2
- print command: §13.5.59 — scale vector always printed as first column
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

    # Retry strategies for convergence failures.
    # Each dict supplies an .options line inserted into the deck.
    # References: ngspice manual §11.1.2 (OP/DC options), §11.1.4 (SRCSTEPS).
    RETRY_STRATEGIES = [
        # Strategy 0: Default settings — let ngspice use its own auto-aids
        #             (built-in gmin stepping + source stepping per §11.3.5)
        {},

        # Strategy 1: Tighter tolerances — can help circuits that oscillate
        #             around the solution due to floating-point noise.
        #             RELTOL default 1e-3; ABSTOL default 1e-12 (§11.1.2).
        {'options': 'reltol=1e-5 abstol=1e-13'},

        # Strategy 2: Add shunt resistors (RSHUNT) to resolve floating nodes /
        #             ill-conditioned matrices (§11.1.2.1).  RSHUNT requires
        #             ngspice to be compiled with XSPICE support (standard in
        #             all major distributions).  1 TΩ value per manual example.
        #             Also raises GMIN to add small conductances to all devices.
        {'options': 'gmin=1e-11 rshunt=1e12'},

        # Strategy 3: Increase DC iteration limits.  ITL1 is the per-step DC
        #             iteration limit (default 100); ITL2 is the DC transfer-
        #             curve limit (default 50).  Per §11.1.2.
        #             NOTE: method=gear was previously used here but that option
        #             only applies to TRANSIENT analysis (§11.1.4) and has no
        #             effect on DC sweeps.
        {'options': 'itl1=200 itl2=100'},

        # Strategy 4: Explicit source stepping.  SRCSTEPS forces all supplies
        #             to ramp from 0 → 100% in the given number of steps (§11.1.2).
        {'options': 'srcsteps=10'},
    ]

    def __init__(self, ngspice_bin='ngspice', timeout=None):
        """
        Args:
            ngspice_bin: Path to ngspice executable
            timeout: Simulation timeout in seconds (None = no timeout)
        """
        self.ngspice_bin = ngspice_bin
        self.timeout = timeout

    @staticmethod
    def _strip_end_directive(netlist: str) -> str:
        """
        Remove .END and analysis directives from a netlist string before
        embedding it in a simulation deck.

        Per SPICE 3F5 §2, .END marks the absolute end of the circuit
        description.  When the netlist text is embedded inside a larger deck
        (which adds .DC / .AC / .control / .endc / .end of its own), any .END
        in the embedded portion would terminate parsing of the *entire* deck
        before the analysis commands are reached — causing a silent simulation
        failure where ngspice exits with no data.

        Also removes analysis directives (.TRAN, .DC, .AC, .PRINT, .PLOT, .PROBE)
        and control blocks (.control/.endc) since the pipeline adds its own.
        Having duplicate directives causes ngspice to produce unexpected output.

        Preserves:
          .ENDS  — subcircuit end directive
          .ENDL  — library section end directive
        """
        out = []
        in_control_block = False

        for line in netlist.splitlines():
            upper = line.strip().upper()

            # Track .control/.endc blocks
            if upper.startswith('.CONTROL'):
                in_control_block = True
                continue  # Skip this line
            if upper.startswith('.ENDC'):
                in_control_block = False
                continue  # Skip this line

            # Skip lines inside .control blocks
            if in_control_block:
                continue

            # Check for .END (but preserve .ENDS and .ENDL)
            is_end = (
                upper.startswith('.END')
                and not upper.startswith('.ENDS')
                and not upper.startswith('.ENDL')
            )

            # Check for analysis directives
            is_analysis = (
                upper.startswith('.TRAN ') or
                upper.startswith('.DC ') or
                upper.startswith('.AC ') or
                upper.startswith('.PRINT ') or
                upper.startswith('.PLOT ') or
                upper.startswith('.PROBE ')
            )

            # Keep line if it's not .END or an analysis directive
            if not is_end and not is_analysis:
                out.append(line)

        return '\n'.join(out)

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
        # Build complete SPICE deck with wrdata output file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            data_file = f.name

        deck = self._build_dc_sweep_deck(netlist, sweep_params, strategy, data_file)

        try:
            # Execute ngspice
            output = self._execute_ngspice(deck)

            # Read wrdata output file
            results = self._parse_dc_sweep_wrdata(
                data_file,
                sweep_params['sweep_var'],
                sweep_params['observe']
            )

            # Validate results
            if not results or len(results[sweep_params['sweep_var']]) == 0:
                raise NgspiceError("No data points in simulation output")

            return results
        finally:
            # Clean up data file
            Path(data_file).unlink(missing_ok=True)

    def _build_dc_sweep_deck(self, netlist, sweep_params, strategy, data_file=None):
        """
        Build complete SPICE deck for DC sweep

        Args:
            netlist: Base netlist
            sweep_params: Sweep parameters
            strategy: Options strategy
            data_file: Optional path to write data with wrdata

        Returns:
            str: Complete SPICE deck
        """
        sweep_var = sweep_params['sweep_var']
        start = sweep_params['start']
        stop = sweep_params['stop']
        step = sweep_params['step']
        observe = sweep_params['observe']

        # Resolve node name → source device name for the .dc command
        # (ngspice .dc requires source names like "VGS", not node names like "vg")
        sweep_src = self._find_voltage_source_for_node(netlist, sweep_var)

        # Build observe list - wrdata uses vector names directly (node names)
        # Don't use v() syntax - just the node name
        observe_list = []
        for v in observe:
            # Strip v() wrapper if present
            if v.startswith('v(') and v.endswith(')'):
                observe_list.append(v[2:-1])
            else:
                observe_list.append(v)

        # Build options line
        options_line = ""
        if 'options' in strategy:
            options_line = f".options {strategy['options']}\n"

        # Strip any .END directives from the embedded netlist.  Per SPICE 3F5
        # §2, .END terminates the *entire* input file; if the user's netlist
        # contains .END and we embed it verbatim, ngspice stops parsing before
        # it ever reaches the .dc / .control commands below.
        clean_netlist = self._strip_end_directive(netlist)

        # Build control block - use wrdata instead of print
        # wrdata with wr_singlescale outputs: v-sweep column first, then all observe variables
        if data_file:
            # Use set wr_singlescale to write a single scale column (v-sweep)
            control_cmd = f"set wr_singlescale\nwrdata {data_file} {' '.join(observe_list)}"
        else:
            # Fallback to print (for backwards compatibility)
            observe_list_plain = [v for v in observe if v != sweep_var]
            control_cmd = f"print {' '.join(observe_list_plain)}"

        # Build complete deck
        # Use sweep_src (resolved source name) in .dc command, not sweep_var (node name)
        deck = f"""* Auto-generated DC sweep deck
{clean_netlist}

{options_line}
.dc {sweep_src} {start} {stop} {step}

.control
run
{control_cmd}
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
            sweep_params,  # Pass full params for grid size calculation
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

        # Strip .END before embedding (see _build_dc_sweep_deck for rationale).
        clean_netlist = self._strip_end_directive(netlist)

        return f"""* Auto-generated 2D DC sweep deck
{clean_netlist}

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
                                   observe_vars, sweep_params=None):
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
                        # Normalise the column header to a plain node name so
                        # we can match it against the variable names we asked
                        # for.  ngspice may output:
                        #   "vin"      — bare name (most common in control mode)
                        #   "v(vin)"   — parenthesised form (some versions)
                        #   "v-sweep"  — the automatic scale column (skip)
                        col_lo   = col.lower()
                        vm = re.match(r'^v\(([^)]+)\)$', col_lo)
                        norm_col = vm.group(1) if vm else col_lo
                        for var in all_vars:
                            if norm_col == var.lower() or col_lo == var.lower():
                                all_data[var].append(values[i])
                                break
                except (ValueError, IndexError):
                    continue

        import numpy as np
        sv1_arr = np.array(all_data[sweep_var_1])
        sv2_arr = np.array(all_data[sweep_var_2])

        if len(sv1_arr) == 0 or len(sv2_arr) == 0:
            return {}

        # Calculate expected grid size from sweep parameters
        if sweep_params:
            # Calculate number of points from start, stop, step
            n1 = int(round((sweep_params['stop_1'] - sweep_params['start_1']) / sweep_params['step_1'])) + 1
            n2 = int(round((sweep_params['stop_2'] - sweep_params['start_2']) / sweep_params['step_2'])) + 1

            # Extract unique values by sampling at expected intervals
            unique_1 = sv1_arr[::n2][:n1]
            unique_2 = sv2_arr[:n2]
        else:
            # Fallback to unique detection (old behavior)
            unique_1 = np.unique(sv1_arr)
            unique_2 = np.unique(sv2_arr)
            n1, n2 = len(unique_1), len(unique_2)

        results = {sweep_var_1: unique_1, sweep_var_2: unique_2}
        for var in observe_vars:
            flat = np.array(all_data[var])
            results[var] = flat.reshape((n1, n2)) if len(flat) == n1 * n2 else flat

        return results

    # ── Transient analysis ───────────────────────────────────────────────

    def tran_sweep(self, netlist, tran_params):
        """
        Run transient analysis (.TRAN) with a PULSE-injected signal source.

        Characterizes circuit dynamics by replacing the named signal source
        with a PULSE waveform and recording the time-domain response.

        This method is a standalone tool for functional verification and
        circuit characterization.  Static Verilog-AMS behavioral models
        (V(out) <+ f(V(in))) cannot match transient waveforms, so tran_sweep
        results are NOT fed into the AI NRMSE loop — use dc_sweep for that.

        Args:
            netlist: SPICE netlist as string
            tran_params: Dict with:
                - tstep:         Output time step (seconds)
                - tstop:         Stop time (seconds)
                - observe:       List of node names to record
                - signal_source: Device name to replace with PULSE (e.g. 'Vin')
                - tstart:        Output start time (default 0.0)
                - v_low:         PULSE low voltage  (default 0.0)
                - v_high:        PULSE high voltage (default 1.8)
                - pulse_delay:   PULSE TD  (default tstop * 0.1)
                - pulse_rise:    PULSE TR  (default tstep)
                - pulse_fall:    PULSE TF  (default tstep)
                - pulse_width:   PULSE PW  (default tstop * 0.4)
                - pulse_period:  PULSE PER (default tstop)

        Returns:
            dict: {'time': np.array, node_name: np.array, ...}

        Per ngspice manual §11.3.3: .tran tstep tstop <tstart>
        PULSE syntax per §4.1: PULSE(v1 v2 td tr tf pw per)
        Output format per §13.5.59: same tabular format as DC sweep,
        with 'time' as the scale vector (first column after Index).
        """
        for strategy_idx, strategy in enumerate(self.RETRY_STRATEGIES):
            try:
                deck    = self._build_tran_deck(netlist, tran_params, strategy)
                output  = self._execute_ngspice(deck)
                observe = tran_params['observe']
                results = self._parse_tran_output(output, observe)
                if not results or len(results.get('time', [])) == 0:
                    raise NgspiceError("No data points in transient simulation output")
                return results
            except NgspiceError as e:
                if strategy_idx == len(self.RETRY_STRATEGIES) - 1:
                    raise NgspiceError(
                        f"All retry strategies failed. Last error: {e}")

    def _build_tran_deck(self, netlist, tran_params, strategy):
        """
        Build complete SPICE deck for transient analysis.

        Replaces the named signal source with a PULSE waveform (§4.1):
            Vname N+ N- PULSE(v_low v_high delay rise fall width period)

        Device name matching uses tokens[0].upper() == signal_src.upper()
        (exact, not substring) — same guard used in _build_ac_sweep_deck
        to prevent corrupting unrelated sources such as 'VDD vin_supply 0'.
        """
        tstep        = tran_params['tstep']
        tstop        = tran_params['tstop']
        tstart       = tran_params.get('tstart', 0.0)
        observe      = tran_params['observe']
        signal_src   = tran_params['signal_source']
        v_low        = tran_params.get('v_low',        0.0)
        v_high       = tran_params.get('v_high',       1.8)
        pulse_delay  = tran_params.get('pulse_delay',  tstop * 0.1)
        pulse_rise   = tran_params.get('pulse_rise',   tstep)
        pulse_fall   = tran_params.get('pulse_fall',   tstep)
        pulse_width  = tran_params.get('pulse_width',  tstop * 0.4)
        pulse_period = tran_params.get('pulse_period', tstop)

        # Replace signal source with PULSE stimulus.  Keep only the first
        # three tokens (device, N+, N-) and append the PULSE specification.
        pulse_spec = (f"PULSE({v_low} {v_high} {pulse_delay} "
                      f"{pulse_rise} {pulse_fall} "
                      f"{pulse_width} {pulse_period})")
        modified = []
        for ln in netlist.split('\n'):
            stripped = ln.strip()
            if stripped and not stripped.startswith('*') and not stripped.startswith('.'):
                tokens = stripped.split()
                if tokens and tokens[0].upper() == signal_src.upper():
                    if len(tokens) >= 3:
                        ln = f"{tokens[0]} {tokens[1]} {tokens[2]} {pulse_spec}"
            modified.append(ln)
        netlist_modified = '\n'.join(modified)

        # Strip .END before embedding (see _build_dc_sweep_deck for rationale).
        clean_netlist = self._strip_end_directive(netlist_modified)

        options_line  = (f".options {strategy['options']}\n"
                         if 'options' in strategy else "")
        observe_list  = ' '.join(observe)
        tstart_clause = f" {tstart}" if tstart != 0.0 else ""

        return f"""* Auto-generated transient sweep deck
{clean_netlist}

{options_line}
.tran {tstep} {tstop}{tstart_clause}

.control
run
print {observe_list}
quit
.endc

.end
"""

    def _parse_tran_output(self, output, observe_vars):
        """
        Parse ngspice transient (.TRAN) output.

        The tabular format produced by the .control 'print' command is
        identical to DC sweep output (§13.5.59): the scale vector ('time')
        is always the first data column (after the Index column).

        Delegates to _parse_dc_sweep_output with sweep_var='time'.

        Returns:
            dict: {'time': np.array, node_name: np.array, ...}
        """
        return self._parse_dc_sweep_output(output, 'time', observe_vars)

    def transient_analysis(self, netlist, tran_params):
        """
        Run basic transient analysis (.TRAN) for oscillators and time-domain circuits.

        Unlike tran_sweep(), this method does NOT inject a PULSE source.
        It simply runs .TRAN with UIC (Use Initial Conditions) to observe
        the natural time-domain behavior of the circuit (e.g., oscillators).

        Args:
            netlist: SPICE netlist as string
            tran_params: Dict with:
                - tstep:   Time step for output (default: tstop/1000)
                - tstop:   End time for simulation (required)
                - tstart:  Start time for saving data (default: 0)
                - tmax:    Maximum internal timestep (default: tstep)
                - observe: List of node names to observe
                - uic:     Use initial conditions (default: False)

        Returns:
            dict: {'time': np.array, node_name: np.array, ...}
        """
        deck = self._build_transient_deck(netlist, tran_params)
        output = self._execute_ngspice(deck)
        return self._parse_transient_output(output, tran_params.get('observe', []))

    def _build_transient_deck(self, netlist, tran_params):
        """
        Build SPICE deck for basic transient analysis (no source modification).

        Args:
            netlist: Original SPICE netlist
            tran_params: Transient parameters dict

        Returns:
            str: Complete SPICE deck with .control block
        """
        # Extract parameters
        tstop = tran_params['tstop']
        tstep = tran_params.get('tstep', tstop / 1000.0)
        tstart = tran_params.get('tstart', 0.0)
        tmax = tran_params.get('tmax', tstep)
        observe = tran_params.get('observe', [])
        uic = tran_params.get('uic', False)

        # Strip .END from netlist
        netlist_clean = self._strip_end_directive(netlist)

        # Build .TRAN directive
        # Format: .TRAN tstep tstop <tstart> <tmax> <UIC>
        tran_directive = f".TRAN {tstep:.12e} {tstop:.12e}"
        if tstart > 0:
            tran_directive += f" {tstart:.12e}"
        if tmax != tstep:
            tran_directive += f" {tmax:.12e}"
        if uic:
            tran_directive += " UIC"

        # Build print statement for observed nodes
        print_vars = ['time'] + [f'v({node})' for node in observe]
        print_stmt = 'print ' + ' '.join(print_vars)

        # Assemble deck
        deck = f"""{netlist_clean}

{tran_directive}

.control
run
{print_stmt}
quit
.endc

.END
"""
        return deck

    def _parse_transient_output(self, output, observe_vars):
        """
        Parse transient analysis output.

        Delegates to the same parser used for DC sweep and tran_sweep,
        since the tabular format is identical.

        Args:
            output: Raw ngspice output
            observe_vars: List of node names

        Returns:
            dict: {'time': np.array, node_name: np.array, ...}
        """
        return self._parse_dc_sweep_output(output, 'time', observe_vars)

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

        # Add AC specification to the V or I source driving input_node if not
        # already present in the netlist.
        #
        # Guard check: scan source lines (V or I, per §4.1/§4.2) for an
        # existing 'AC' keyword.  A simple f'ac {ac_mag}' substring search
        # fails if the netlist already has 'AC 1' (integer) but ac_mag=1.0
        # (float).  A bare 'ac' search would falsely match the '.ac' analysis
        # command itself, so we restrict the check to source element lines.
        _ac_already_set = any(
            re.search(r'\bAC\b', ln, re.I)
            for ln in netlist.splitlines()
            if ln.strip() and ln.strip()[0].upper() in ('V', 'I')
        )
        if not _ac_already_set:
            modified = []
            for ln in netlist.split('\n'):
                stripped = ln.strip()
                # Handle both V sources (§4.1) and I sources (§4.2):
                # both accept the same AC <ACMAG <ACPHASE>> syntax.
                # Use token-level matching (tokens[1] == input_node) rather
                # than a substring search to avoid accidentally modifying the
                # wrong source (e.g. 'VDD vin_supply 0' when input_node='vin').
                if stripped and stripped[0].upper() in ('V', 'I'):
                    tokens = stripped.split()
                    # tokens[0]=device, tokens[1]=N+ (positive node per §4.1/§4.2)
                    if (len(tokens) >= 2
                            and tokens[1].lower() == input_node.lower()):
                        ln = ln.rstrip() + (
                            f' AC {ac_mag}' if 'dc' in ln.lower()
                            else f' DC 0 AC {ac_mag}')
                modified.append(ln)
            netlist = '\n'.join(modified)

        # Strip .END before embedding (see _build_dc_sweep_deck for rationale).
        netlist = self._strip_end_directive(netlist)

        observe_list = []
        for node in output_nodes:
            nc = node.replace('net:', '')
            # vdb() and vp() are per ngspice manual §11.6.2:
            # VDB = 20·log10(magnitude), VP = phase in degrees.
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
        # Strip .END before embedding (see _build_dc_sweep_deck for rationale).
        clean_netlist = self._strip_end_directive(netlist)

        # Build complete SPICE deck
        deck = f"""* Auto-generated DC OP deck
{clean_netlist}

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

            # Check for convergence errors.  Use the specific phrase "no
            # convergence" rather than bare "convergence": ngspice may print
            # informational messages about convergence aids being applied
            # (gmin stepping, source stepping) even when the simulation
            # ultimately succeeds, so a bare 'convergence' match would
            # produce false positives and discard good data.
            if 'no convergence' in result.stderr.lower():
                raise NgspiceError(f"Convergence failure: {result.stderr}")

            return result.stdout

        except subprocess.TimeoutExpired:
            timeout_msg = f"{self.timeout}s" if self.timeout else "unknown"
            raise NgspiceError(f"Simulation timeout after {timeout_msg}")

        finally:
            # Clean up temporary file
            Path(deck_file).unlink(missing_ok=True)

    def _parse_dc_sweep_wrdata(self, data_file, sweep_var, observe_vars):
        """
        Parse ngspice wrdata output file from DC sweep

        wrdata format with set wr_singlescale (space-separated):
            v-sweep_val  obs1_val  obs2_val  ...
            v-sweep_val  obs1_val  obs2_val  ...

        First column is v-sweep (sweep variable), then observe variables in order

        Args:
            data_file: Path to wrdata output file
            sweep_var: Name of sweep variable
            observe_vars: List of variables to observe

        Returns:
            dict: {var_name: numpy_array}
        """
        results = {sweep_var: [], **{v: [] for v in observe_vars}}

        try:
            with open(data_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # Parse space-separated data
                    # Format: v-sweep obs1 obs2 ...
                    tokens = line.split()

                    if len(tokens) < 1:
                        continue

                    try:
                        # All tokens are data values (no index column)
                        values = [float(t) for t in tokens]

                        if len(values) < 1:
                            continue

                        # First value is always v-sweep (the sweep variable)
                        sweep_val = values[0]
                        observe_vals = values[1:]

                        results[sweep_var].append(sweep_val)

                        # Map remaining values to observe variables
                        for i, obs_var in enumerate(observe_vars):
                            if i < len(observe_vals):
                                results[obs_var].append(observe_vals[i])

                    except (ValueError, IndexError):
                        continue

        except FileNotFoundError:
            # File doesn't exist - return empty results
            pass

        # Convert to numpy arrays
        results = {k: np.array(v) for k, v in results.items()}

        return results

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

        # Strip .END before embedding (see _build_dc_sweep_deck for rationale).
        clean_netlist = self._strip_end_directive(netlist)

        # Build complete SPICE deck
        deck = f"""* Auto-generated AC parameter extraction
{clean_netlist}

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

            # Parse parameters within device section.
            # Use a word-boundary check so that "gm" does NOT match "gmb" lines.
            # (plain startswith('gm') would match both "gm  6e-5" and "gmb  0")
            if in_device_section:
                for param in ['gm', 'gds', 'gmb']:
                    # Match the parameter name followed by whitespace or EOL
                    if (line_stripped == param
                            or line_stripped.startswith(param + ' ')
                            or line_stripped.startswith(param + '\t')):
                        tokens = line_stripped.split()
                        if len(tokens) >= 2:
                            try:
                                results[param] = float(tokens[1])
                            except ValueError:
                                pass

        return results

    def extract_ac_params_transient(self, netlist, device_name,
                                      vg_dc=None, vd_dc=None,
                                      perturbation_mv=10.0,
                                      freq_hz=1e6,
                                      n_periods=5):
        """
        Extract small-signal AC parameters (gm, gds) using transient analysis
        with AC perturbation.

        SIMPLIFIED IMPLEMENTATION - builds custom test circuit from scratch
        rather than modifying arbitrary netlists. This approach is more robust
        and easier to debug.

        This is an alternative to extract_ac_params() that uses transient
        simulation instead of .OP analysis. Useful when:
        - The DC operating point analysis fails or is unreliable
        - You want to verify results against the standard .OP+show method
        - You need to extract parameters under specific bias conditions

        Method:
          1. For gm: inject small SIN at gate, measure drain current AC amplitude
             gm = ΔI_d / ΔV_gs (at constant Vds)
          2. For gds: inject small SIN at drain, measure drain current AC amplitude
             gds = ΔI_d / ΔV_ds (at constant Vgs)

        Args:
            netlist: SPICE netlist containing device model definition
            device_name: Name of device to characterize (e.g., "M1")
            vg_dc: DC gate voltage for bias point (default: auto from netlist)
            vd_dc: DC drain voltage for bias point (default: auto from netlist)
            perturbation_mv: AC perturbation amplitude in mV (default 10 mV)
            freq_hz: Perturbation frequency in Hz (default 1 MHz)
            n_periods: Number of periods to simulate (default 5)

        Returns:
            dict: {'gm': value, 'gds': value, 'vg_dc': value, 'vd_dc': value}

        Example:
            runner = NgspiceRunner()
            netlist = '''
                .model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
            '''
            # Characterize NMOS at Vgs=0.9V, Vds=1.8V
            params = runner.extract_ac_params_transient(
                netlist, 'M1', vg_dc=0.9, vd_dc=1.8)
            print(f"gm={params['gm']:.3e} S, gds={params['gds']:.3e} S")
        """
        # Parse device from original netlist to get model and parameters
        device_info = self._parse_single_device(netlist, device_name)

        if not device_info:
            # Device not in netlist - use defaults
            device_info = {
                'type': 'M',
                'model': 'NMOS',
                'params': 'W=10u L=1u'
            }

        # Auto-detect bias if not provided
        if vg_dc is None:
            vg_dc = 0.9  # Typical NMOS bias
        if vd_dc is None:
            vd_dc = 1.8  # Typical supply voltage

        period = 1.0 / freq_hz
        tstop = n_periods * period
        tstep = period / 100  # 100 points per period

        perturb_v = perturbation_mv / 1000.0  # mV → V

        # ── Extract gm: perturb gate, measure drain current ────────────
        gm = self._measure_gm_transient(
            device_info, vg_dc, vd_dc, perturb_v, freq_hz, tstep, tstop, netlist)

        # ── Extract gds: perturb drain, measure drain current ───────────
        gds = self._measure_gds_transient(
            device_info, vg_dc, vd_dc, perturb_v, freq_hz, tstep, tstop, netlist)

        return {
            'gm': gm,
            'gds': gds,
            'vg_dc': vg_dc,
            'vd_dc': vd_dc,
            'perturbation_mv': perturbation_mv,
            'frequency_hz': freq_hz
        }

    def _parse_single_device(self, netlist, device_name):
        """
        Extract device model and parameters from netlist.

        Returns:
            dict: {'type': 'M'/'Q'/'J', 'model': str, 'params': str} or None
        """
        for line in netlist.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('*') or stripped.startswith('.'):
                continue

            tokens = stripped.split()
            if not tokens:
                continue

            if tokens[0].upper() == device_name.upper() and len(tokens) >= 5:
                dtype = tokens[0][0].upper()
                model = tokens[5] if len(tokens) > 5 else 'NMOS'
                params = ' '.join(tokens[6:]) if len(tokens) > 6 else 'W=10u L=1u'

                return {
                    'type': dtype,
                    'model': model,
                    'params': params
                }
        return None

    def _measure_gm_transient(self, device_info, vg_dc, vd_dc,
                              perturb_v, freq_hz, tstep, tstop, model_netlist):
        """
        Measure gm by applying AC perturbation to gate.

        Test circuit:
            Vg: gate_pert ---[Vpert_gm]--- gate --- M1 --- Vmeas_drain --- vd_dc
                     |                      |
                   SIN                     |
                                       source (gnd)
        """
        # Extract model definitions from original netlist
        model_lines = [l for l in model_netlist.splitlines()
                      if l.strip().startswith('.model')]
        models = '\n'.join(model_lines)

        dtype = device_info.get('type', 'M')
        model = device_info.get('model', 'NMOS')
        params = device_info.get('params', 'W=10u L=1u')

        # Build test circuit
        # The perturbation is DC bias + small AC signal
        test_netlist = f"""* gm extraction test circuit
* Device under test with AC perturbation at gate
Vg_dc gate_drive 0 DC {vg_dc}
Vpert_gm gate gate_drive SIN(0 {perturb_v} {freq_hz})
Vd_dc vd_supply 0 DC {vd_dc}
Vmeas_drain vd_supply vd DC 0

{dtype}1 vd gate 0 0 {model} {params}

{models}
"""

        deck = self._build_transient_perturbation_deck(
            test_netlist, tstep, tstop, 'time i(vmeas_drain)')

        try:
            output = self._execute_ngspice(deck)
            results = self._parse_tran_output(output, ['i(vmeas_drain)'])

            if 'time' not in results or 'i(vmeas_drain)' not in results:
                return 0.0

            time = results['time']
            i_drain = results['i(vmeas_drain)']

            # Extract AC amplitude from steady-state (second half)
            mid_idx = len(time) // 2
            i_ac = i_drain[mid_idx:]
            i_amplitude = (np.max(i_ac) - np.min(i_ac)) / 2.0

            # gm = ΔI_d / ΔV_gs
            gm = i_amplitude / perturb_v if perturb_v > 0 else 0.0

            return float(gm)

        except NgspiceError:
            return 0.0

    def _measure_gds_transient(self, device_info, vg_dc, vd_dc,
                               perturb_v, freq_hz, tstep, tstop, model_netlist):
        """
        Measure gds by applying AC perturbation to drain.

        Test circuit:
            Vg: vg_dc --- gate --- M1 --- Vmeas_drain --- vd_pert ---[Vpert_gds]--- vd_dc
                                   |                            |
                              source (gnd)                    SIN
        """
        model_lines = [l for l in model_netlist.splitlines()
                      if l.strip().startswith('.model')]
        models = '\n'.join(model_lines)

        dtype = device_info.get('type', 'M')
        model = device_info.get('model', 'NMOS')
        params = device_info.get('params', 'W=10u L=1u')

        # Build test circuit
        test_netlist = f"""* gds extraction test circuit
* Device under test with AC perturbation at drain
Vg_dc gate 0 DC {vg_dc}
Vd_dc vd_supply 0 DC {vd_dc}
Vpert_gds vd_supply vd_pert SIN(0 {perturb_v} {freq_hz})
Vmeas_drain vd_pert vd DC 0

{dtype}1 vd gate 0 0 {model} {params}

{models}
"""

        deck = self._build_transient_perturbation_deck(
            test_netlist, tstep, tstop, 'time i(vmeas_drain)')

        try:
            output = self._execute_ngspice(deck)
            results = self._parse_tran_output(output, ['i(vmeas_drain)'])

            if 'time' not in results or 'i(vmeas_drain)' not in results:
                return 0.0

            time = results['time']
            i_drain = results['i(vmeas_drain)']

            # Extract AC amplitude from steady-state
            mid_idx = len(time) // 2
            i_ac = i_drain[mid_idx:]
            i_amplitude = (np.max(i_ac) - np.min(i_ac)) / 2.0

            # gds = ΔI_d / ΔV_ds
            gds = i_amplitude / perturb_v if perturb_v > 0 else 0.0

            return float(gds)

        except NgspiceError:
            return 0.0

    def _build_transient_perturbation_deck(self, netlist, tstep, tstop,
                                           measure_vars):
        """
        Build SPICE deck for transient perturbation analysis.

        Args:
            netlist: Test circuit netlist
            tstep: Time step
            tstop: Stop time
            measure_vars: Space-separated variables to print (e.g., 'time i(vmeas)')

        Returns:
            str: Complete SPICE deck
        """
        clean_netlist = self._strip_end_directive(netlist)

        return f"""* Auto-generated transient perturbation deck
{clean_netlist}

.tran {tstep} {tstop}

.control
run
print {measure_vars}
quit
.endc

.end
"""


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
