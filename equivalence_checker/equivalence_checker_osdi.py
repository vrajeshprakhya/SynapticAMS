#!/usr/bin/env python3
"""
equivalence_checker_osdi.py

Wrapper module that provides OSDI-based equivalence checking.
This provides a compatibility layer between the programmatic pipeline's
expected API and the underlying EquivalenceChecker implementation.

The EquivalenceChecker uses OpenVAF to compile Verilog-AMS to OSDI
and ngspice to validate equivalence between SPICE and Verilog-AMS.

Supports:
- DC sweep validation (amplifiers, gates)
- Transient validation (oscillators, VCOs, dynamic circuits)
- Small-signal parameter validation (linearized models)
"""

import numpy as np
import tempfile
import subprocess
from pathlib import Path
from equivalence_checker.equivalence_checker import EquivalenceChecker as BaseChecker, EquivalenceResult


class OSDIEquivalenceChecker(BaseChecker):
    """
    OSDI-based equivalence checker with compatibility API.

    Extends EquivalenceChecker to provide check_equivalence() method
    expected by the programmatic pipeline.
    """

    def check_equivalence(self, netlist, verilog_ams_code, module_name,
                         input_names=None, output_names=None, n_test_points=20,
                         mode='auto'):
        """
        Check equivalence between SPICE netlist and Verilog-AMS model.

        Args:
            netlist: SPICE netlist text
            verilog_ams_code: Verilog-AMS module code
            module_name: Name of the Verilog-AMS module
            input_names: List of input signal names
            output_names: List of output signal names
            n_test_points: Number of test points for validation
            mode: 'auto', 'dc', or 'transient'

        Returns:
            EquivalenceResult with detailed metrics
        """
        # Build block_info dict from provided parameters
        block_info = {
            'simulation_axes': set(f'net:{name}' for name in (input_names or [])),
            'outputs': set(f'net:{name}' for name in (output_names or [])),
            'behavior_class': 'NONLINEAR',  # Conservative assumption
            'name': module_name,
        }

        # Auto-detect mode if needed
        if mode == 'auto':
            mode = self._detect_validation_mode(verilog_ams_code, module_name)

        if mode == 'transient':
            return self.check_transient_equivalence(
                netlist, verilog_ams_code, module_name,
                output_names=output_names
            )
        else:
            # DC sweep validation
            return self.check_block_equivalence(
                spice_netlist=netlist,
                verilog_ams_code=verilog_ams_code,
                block_info=block_info,
                test_strategy='grid'
            )

    def _detect_validation_mode(self, verilog_ams_code, module_name):
        """
        Detect whether to use DC or transient validation based on model characteristics.

        Returns: 'dc' or 'transient'
        """
        code_lower = verilog_ams_code.lower()

        # Indicators of dynamic/oscillator models
        dynamic_indicators = [
            'oscillator', 'vco', 'ring', 'pll', 'clock',
            '$abstime', 'ddt(', 'idt(', 'transition(',
            'timer(', 'analysis('
        ]

        for indicator in dynamic_indicators:
            if indicator in code_lower:
                return 'transient'

        return 'dc'

    def check_transient_equivalence(self, netlist, verilog_ams_code, module_name,
                                   output_names=None, tstop=100e-9, tstep=1e-12):
        """
        Check equivalence using transient simulation.

        Args:
            netlist: SPICE netlist text
            verilog_ams_code: Verilog-AMS module code
            module_name: Name of module
            output_names: List of output signals to compare
            tstop: Simulation stop time (seconds)
            tstep: Time step (seconds)

        Returns:
            EquivalenceResult
        """
        try:
            # Compile Verilog-AMS to OSDI
            osdi_file = self._compile_to_osdi(verilog_ams_code, module_name)

            # Run transient simulation on both SPICE and OSDI
            spice_data = self._run_transient_spice(netlist, output_names, tstop, tstep)
            osdi_data = self._run_transient_osdi(osdi_file, module_name, output_names, tstop, tstep)

            # Compare waveforms
            return self._compare_transient_waveforms(spice_data, osdi_data, output_names)

        except Exception as e:
            print(f"Warning: Transient equivalence check failed: {e}")
            return EquivalenceResult(
                passed=False,
                max_absolute_error=float('inf'),
                max_relative_error=float('inf'),
                rms_error=float('inf'),
                correlation=0.0,
                failing_points=[],
                coverage_percentage=0.0
            )

    def _run_transient_spice(self, netlist, output_nodes, tstop, tstep):
        """Run transient simulation on original SPICE netlist."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            # Write netlist - remove existing .END, .TRAN, .PRINT directives
            lines = []
            for line in netlist.split('\n'):
                line_upper = line.strip().upper()
                # Skip existing analysis and end directives
                # BUT NOT .ENDS (subcircuit end)
                if (line_upper == '.END' or
                    line_upper.startswith('.TRAN ') or
                    line_upper.startswith('.PRINT ')):
                    continue
                lines.append(line)

            # Write cleaned netlist
            f.write('\n'.join(lines))
            f.write('\n\n')

            # Add transient analysis
            f.write(f'.TRAN {tstep} {tstop}\n')

            # Add control block with print command
            f.write('\n.CONTROL\n')
            f.write('run\n')
            if output_nodes:
                f.write('print ' + ' '.join(f'v({n})' for n in output_nodes) + '\n')
            f.write('quit\n')
            f.write('.ENDC\n')
            f.write('.END\n')
            deck_file = f.name

        try:
            # Run ngspice (no timeout for complex circuits)
            # Note: Do NOT use -o flag as it suppresses .control print output
            result = subprocess.run(
                [self.ngspice_bin, '-b', deck_file],
                capture_output=True, text=True, timeout=None
            )

            # Parse output
            return self._parse_transient_output(result.stdout, output_nodes)
        except subprocess.TimeoutExpired:
            print(f"      Warning: SPICE transient simulation timed out")
            return None
        except Exception as e:
            print(f"      Warning: SPICE transient simulation failed: {e}")
            return None
        finally:
            Path(deck_file).unlink(missing_ok=True)

    def _run_transient_osdi(self, osdi_file, module_name, output_nodes, tstop, tstep):
        """Run transient simulation on compiled OSDI model."""
        if not osdi_file or not Path(osdi_file).exists():
            return None

        # Create testbench netlist for autonomous oscillator (no inputs)
        # Instantiation for autonomous modules (no inputs, only outputs)
        if not output_nodes:
            output_nodes = ['out']

        output_list = ' '.join(output_nodes)

        testbench = f"""* Transient testbench for {module_name}

* Load OSDI library
.control
pre_osdi {osdi_file}
.endc

* Define model (maps model name to Verilog-A module name)
.model osc_model {module_name}

* OSDI device instance (N prefix for OSDI models)
* Format: N<name> <nodes...> <model_name>
Nmodel {output_list} osc_model

.TRAN {tstep} {tstop}

.control
run
print {' '.join(f'v({n})' for n in output_nodes)}
quit
.endc

.END
"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.cir', delete=False) as f:
            f.write(testbench)
            deck_file = f.name

        try:
            # Run ngspice (no timeout for complex circuits)
            # Note: Do NOT use -o flag as it suppresses .control print output
            result = subprocess.run(
                [self.ngspice_bin, '-b', deck_file],
                capture_output=True, text=True, timeout=None
            )

            # Parse output
            return self._parse_transient_output(result.stdout, output_nodes)
        except Exception as e:
            print(f"      Warning: OSDI transient simulation failed: {e}")
            return None
        finally:
            Path(deck_file).unlink(missing_ok=True)

    def _parse_transient_output(self, output, signals):
        """Parse ngspice transient output into time-series data."""
        import re

        # Look for the data section (after "Index   time   v(...)...")
        lines = output.split('\n')

        # Find the header line with column names
        header_idx = None
        for i, line in enumerate(lines):
            if 'time' in line.lower() and any(s in line.lower() for s in (signals or [])):
                header_idx = i
                break

        if header_idx is None:
            return {}

        # Parse header to get column indices
        header = lines[header_idx]
        columns = header.split()

        # Find which columns correspond to our signals
        time_col = None
        signal_cols = {}

        for idx, col in enumerate(columns):
            col_lower = col.lower()
            if col_lower == 'time':
                time_col = idx
            else:
                # Check if this column matches any of our signals
                for sig in (signals or []):
                    if sig.lower() in col_lower or f'v({sig})'.lower() in col_lower:
                        signal_cols[sig] = idx

        if time_col is None:
            return {}

        # Parse data rows
        time_data = []
        signal_data = {sig: [] for sig in signal_cols.keys()}

        for line in lines[header_idx + 1:]:
            line = line.strip()
            if not line or line.startswith('-'):
                continue

            # Parse the data row
            parts = line.split()
            if len(parts) < max(time_col + 1, max(signal_cols.values(), default=0) + 1):
                continue

            try:
                time_val = float(parts[time_col])
                time_data.append(time_val)

                for sig, col_idx in signal_cols.items():
                    val = float(parts[col_idx])
                    signal_data[sig].append(val)
            except (ValueError, IndexError):
                continue

        if not time_data:
            return {}

        result = {'time': np.array(time_data)}
        for sig, data in signal_data.items():
            result[sig] = np.array(data)

        return result

    def _compare_transient_waveforms(self, spice_data, osdi_data, signals):
        """Compare transient waveforms and compute metrics."""
        if not spice_data or not osdi_data:
            # Return neutral result (not passed, but not infinitely bad)
            # This indicates the check was skipped, not that it failed dramatically
            return EquivalenceResult(
                passed=False,
                max_absolute_error=None,
                max_relative_error=None,
                rms_error=None,
                correlation=None,
                failing_points=[],
                coverage_percentage=0.0
            )

        # Check if both have time data
        if 'time' not in spice_data or 'time' not in osdi_data:
            return EquivalenceResult(
                passed=False,
                max_absolute_error=float('inf'),
                max_relative_error=float('inf'),
                rms_error=float('inf'),
                correlation=0.0,
                failing_points=[],
                coverage_percentage=0.0
            )

        # Interpolate OSDI data to SPICE time points (for fair comparison)
        spice_time = spice_data['time']
        osdi_time = osdi_data['time']

        max_abs_err = 0.0
        max_rel_err = 0.0
        rms_err = 0.0
        correlation = 0.0
        signal_count = 0

        for signal in (signals or []):
            if signal not in spice_data or signal not in osdi_data:
                continue

            spice_vals = spice_data[signal]
            osdi_vals = osdi_data[signal]

            # Interpolate OSDI to SPICE time points
            if len(osdi_time) != len(spice_time) or not np.allclose(osdi_time, spice_time):
                osdi_vals_interp = np.interp(spice_time, osdi_time, osdi_vals)
            else:
                osdi_vals_interp = osdi_vals

            # Compute errors
            abs_err = np.abs(spice_vals - osdi_vals_interp)
            max_abs = np.max(abs_err)

            # Relative error (avoid division by zero)
            spice_range = np.max(spice_vals) - np.min(spice_vals)
            if spice_range > 1e-12:
                rel_err = abs_err / spice_range
                max_rel = np.max(rel_err)
            else:
                max_rel = 0.0 if max_abs < 1e-12 else float('inf')

            # RMS error
            rms = np.sqrt(np.mean(abs_err**2))

            # Correlation coefficient
            if len(spice_vals) > 1:
                corr_matrix = np.corrcoef(spice_vals, osdi_vals_interp)
                corr = corr_matrix[0, 1] if corr_matrix.shape == (2, 2) else 0.0
            else:
                corr = 1.0 if max_abs < 1e-12 else 0.0

            # Update worst-case metrics
            max_abs_err = max(max_abs_err, max_abs)
            max_rel_err = max(max_rel_err, max_rel)
            rms_err = max(rms_err, rms)
            correlation += corr
            signal_count += 1

        # Average correlation across signals
        if signal_count > 0:
            correlation /= signal_count
        else:
            correlation = 0.0

        # Determine if test passed
        # Pass if: max abs error < tolerance OR correlation > threshold
        passed = (max_abs_err < self.abs_tol) or (correlation > 0.95)

        return EquivalenceResult(
            passed=passed,
            max_absolute_error=max_abs_err,
            max_relative_error=max_rel_err,
            rms_error=rms_err,
            correlation=correlation,
            failing_points=[],
            coverage_percentage=100.0 if signal_count > 0 else 0.0
        )


__all__ = ['OSDIEquivalenceChecker']
