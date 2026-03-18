#!/usr/bin/env python3
"""
complete_pipeline.py

End-to-end demonstration: SPICE netlist → Verilog-AMS modules

Shows the complete flow:
1. Parse SPICE netlist
2. Analyze circuit structure
3. Plan simulations
4. Run ngspice
5. Fit transfer functions
6. Generate Verilog-AMS code
7. Save .va files
"""

from pipeline_ext.graph_builder import parse_spice_netlist, build_bipartite_graph
from pipeline_ext.circuit_analyzer import analyze_blocks
from pipeline_ext.simulation_planner import SimulationPlanner
from ngspice_runner import NgspiceRunner
from pipeline_ext.fit_transfer_function import fit_transfer_function
from pipeline_ext.verilog_ams_generator import VerilogAMSGenerator
from pipeline_ext.extract_small_signal_model import extract_small_signal_model
from equivalence_checker import EquivalenceChecker
from spice_flatten import flatten_netlist
import re

# OSDI equivalence checking is optional (requires OpenVAF)
try:
    from equivalence_checker_osdi import OSDIEquivalenceChecker
    OSDI_AVAILABLE = True
except ImportError:
    OSDI_AVAILABLE = False
    OSDIEquivalenceChecker = None

# Oscillator-specific equivalence checking (frequency-domain)
try:
    from oscillator_equivalence import check_oscillator_equivalence
    OSCILLATOR_CHECKER_AVAILABLE = True
except ImportError:
    OSCILLATOR_CHECKER_AVAILABLE = False
    check_oscillator_equivalence = None


def extract_device_bias(netlist_text, device_name):
    """
    Extract DC bias voltages for a device from the netlist.

    Attempts to find the DC operating point by:
    1. Finding the device's terminals in the netlist
    2. Tracing back to voltage sources on those nets
    3. Extracting DC values from the sources

    Args:
        netlist_text: SPICE netlist string
        device_name: Device name (e.g., 'M1')

    Returns:
        dict: {'vg_dc': float or None, 'vd_dc': float or None}
    """
    bias = {'vg_dc': None, 'vd_dc': None}

    # Find device line
    device_terminals = None
    for line in netlist_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('*') or stripped.startswith('.'):
            continue

        tokens = stripped.split()
        if tokens and tokens[0].upper() == device_name.upper():
            if len(tokens) >= 5:
                # MOSFET: M name D G S B model
                device_terminals = {
                    'drain': tokens[1].lower(),
                    'gate': tokens[2].lower(),
                    'source': tokens[3].lower(),
                }
            break

    if not device_terminals:
        # Use defaults
        return {'vg_dc': 0.9, 'vd_dc': 1.8}

    # Find voltage sources connected to gate and drain
    for line in netlist_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('*') or stripped.startswith('.'):
            continue

        tokens = stripped.split()
        if not tokens or tokens[0][0].upper() != 'V':
            continue

        if len(tokens) >= 3:
            # Voltage source: V name N+ N- DC value
            pos_node = tokens[1].lower()

            # Check if this source connects to gate or drain
            if pos_node == device_terminals['gate']:
                # Extract DC voltage
                dc_match = re.search(r'\bDC\s+([\d\.eE+-]+)', stripped, re.I)
                if dc_match:
                    try:
                        bias['vg_dc'] = float(dc_match.group(1))
                    except ValueError:
                        pass
                elif len(tokens) >= 4 and not tokens[3].upper().startswith(('AC', 'PULSE', 'SIN')):
                    # Implicit DC value (4th token)
                    try:
                        bias['vg_dc'] = float(tokens[3].replace('V', ''))
                    except ValueError:
                        pass

            if pos_node == device_terminals['drain']:
                dc_match = re.search(r'\bDC\s+([\d\.eE+-]+)', stripped, re.I)
                if dc_match:
                    try:
                        bias['vd_dc'] = float(dc_match.group(1))
                    except ValueError:
                        pass
                elif len(tokens) >= 4 and not tokens[3].upper().startswith(('AC', 'PULSE', 'SIN')):
                    try:
                        bias['vd_dc'] = float(tokens[3].replace('V', ''))
                    except ValueError:
                        pass

    # Fallback to reasonable defaults
    if bias['vg_dc'] is None:
        bias['vg_dc'] = 0.9
    if bias['vd_dc'] is None:
        bias['vd_dc'] = 1.8

    return bias

def spice_to_verilog_ams(netlist_text, output_dir='.'):
    """
    Complete pipeline: SPICE netlist → Verilog-AMS modules

    Args:
        netlist_text: SPICE netlist as string
        output_dir: Directory to save .va files

    Returns:
        list: Paths to generated .va files
    """
    print("="*70)
    print(" SPICE → VERILOG-AMS PIPELINE")
    print("="*70)

    # Step 0: Flatten netlist (expand subcircuits)
    print("\n[0/7] Flattening netlist (expanding subcircuits)...")
    flat_netlist = flatten_netlist(netlist_text)
    print(f"      Original: {len(netlist_text)} chars")
    print(f"      Flattened: {len(flat_netlist)} chars")

    # Step 1: Parse netlist
    print("\n[1/7] Parsing SPICE netlist...")
    devices = parse_spice_netlist(flat_netlist)
    graph = build_bipartite_graph(devices)
    print(f"      Found {len(devices)} devices")

    # Step 2: Analyze structure
    print("\n[2/7] Analyzing circuit structure...")
    blocks = analyze_blocks(graph)
    print(f"      Identified {len(blocks)} functional blocks")

    for block in blocks:
        print(f"      Block {block['block_id']}:")
        print(f"        Inputs: {block['inputs']}")
        print(f"        Outputs: {block['outputs']}")
        print(f"        Control axes: {block['simulation_axes']}")

    # Step 3: Plan simulations
    print("\n[3/7] Planning simulations...")
    from pipeline_ext.circuit_analyzer import find_constant_nets
    constant_nets = find_constant_nets(graph)

    # Create NgspiceRunner early for independence detection
    runner = NgspiceRunner()

    # Pass netlist and runner to enable independence detection
    planner = SimulationPlanner(graph, constant_nets, netlist=netlist_text, runner=runner)

    # Separate blocks by behavior class
    structural_linear_blocks = [b for b in blocks if b.get('behavior_class') == 'STRUCTURAL_LINEAR']
    small_signal_blocks = [b for b in blocks if b.get('behavior_class') == 'SMALL_SIGNAL_LINEARIZABLE']
    nonlinear_blocks = [b for b in blocks if b.get('behavior_class') == 'NONLINEAR']

    print(f"      Structural linear blocks (passive-only): {len(structural_linear_blocks)}")
    print(f"      Small-signal linearizable blocks: {len(small_signal_blocks)}")
    print(f"      Nonlinear blocks: {len(nonlinear_blocks)}")

    # Plan DC sweeps for both small-signal and nonlinear blocks
    # (both need large-signal DC characterization)
    dc_sweep_blocks = small_signal_blocks + nonlinear_blocks
    all_sweep_plans = []
    for block in dc_sweep_blocks:
        sweep_plans = planner.plan_dc_sweep(block)
        all_sweep_plans.extend(sweep_plans)

    print(f"      Generated {len(all_sweep_plans)} DC sweep plans")

    # Plan transient simulations for ALL blocks (not just oscillators)
    transient_plans = []
    for block in blocks:
        tran_plan = planner.plan_transient(block)
        if tran_plan:
            transient_plans.append({'block': block, 'plan': tran_plan})

    if transient_plans:
        print(f"      Generated {len(transient_plans)} transient simulation plans")

    # Step 4: Run ngspice simulations
    print("\n[4/7] Running ngspice simulations...")
    simulation_results = []
    small_signal_results = []

    # DC sweeps for nonlinear blocks
    for i, plan in enumerate(all_sweep_plans):
        plan_type = plan.get('type', 'dc_sweep')

        if plan_type == 'dc_sweep_2d':
            # 2D sweep
            sweep_var_1 = plan['sweep_var_1']
            sweep_var_2 = plan['sweep_var_2']
            print(f"      2D Sweep {i+1}/{len(all_sweep_plans)}: {sweep_var_1} × {sweep_var_2}")
            print(f"        {sweep_var_1}: [{plan['start_1']:.2f} → {plan['stop_1']:.2f}]")
            print(f"        {sweep_var_2}: [{plan['start_2']:.2e} → {plan['stop_2']:.2e}]", end="")

            try:
                results = runner.dc_sweep_2d(netlist_text, plan)
                n1 = len(results[sweep_var_1])
                n2 = len(results[sweep_var_2])
                print(f" ✓ {n1}×{n2} grid")

                simulation_results.append({
                    'plan': plan,
                    'data': results
                })
            except Exception as e:
                print(f" ✗ Failed: {e}")

        else:
            # 1D sweep
            sweep_var = plan['sweep_var']
            print(f"      1D Sweep {i+1}/{len(all_sweep_plans)}: {sweep_var} "
                  f"[{plan['start']:.2f} → {plan['stop']:.2f}]", end="")

            try:
                results = runner.dc_sweep(netlist_text, plan)
                print(f" ✓ {len(results[sweep_var])} points")

                simulation_results.append({
                    'plan': plan,
                    'data': results
                })
            except Exception as e:
                print(f" ✗ Failed: {e}")

    # Structural linear blocks (passive-only): DC OP + AC frequency sweep
    linear_ac_results = []
    for i, block in enumerate(structural_linear_blocks):
        print(f"      Structural linear block {i+1}/{len(structural_linear_blocks)}: ", end="")

        try:
            # Identify input and output nodes
            inputs = list(block['inputs'])
            outputs = list(block['outputs'])

            if not inputs or not outputs:
                print(f"⚠ No inputs/outputs, skipping")
                continue

            # Filter out ground nodes from inputs
            ground_nodes = {'net:0', 'net:gnd', 'net:GND'}
            signal_inputs = [inp for inp in inputs if inp not in ground_nodes]

            if not signal_inputs:
                print(f"⚠ No non-ground inputs, skipping")
                continue

            # Use first non-ground input as AC source
            input_node = signal_inputs[0].replace('net:', '')
            output_nodes = [o.replace('net:', '') for o in outputs]

            # Run AC sweep
            ac_params = {
                'sweep_type': 'dec',
                'n_points': 10,
                'start_freq': 1,       # 1 Hz
                'stop_freq': 1e9,      # 1 GHz
                'input_node': input_node,
                'output_nodes': output_nodes,
                'ac_magnitude': 1.0
            }

            ac_results = runner.ac_sweep(netlist_text, ac_params)

            # Check if we got valid results
            if len(ac_results['frequency']) > 0:
                print(f"✓ AC sweep complete ({len(ac_results['frequency'])} points)")

                linear_ac_results.append({
                    'block': block,
                    'ac_results': ac_results,
                    'input_node': input_node,
                    'output_nodes': output_nodes
                })
            else:
                print(f"⚠ No AC data, skipping")

        except Exception as e:
            print(f"✗ Failed: {e}")

    # DC operating point + AC parameter extraction for small-signal linearizable blocks
    for i, block in enumerate(small_signal_blocks):
        print(f"      Small-signal block {i+1}/{len(small_signal_blocks)}: extracting AC params...", end="")

        try:
            # Find transistor devices in this block
            transistor_devices = []
            for node in block['nodes']:
                if graph.nodes[node].get('kind') == 'device':
                    device_type = graph.nodes[node].get('device_type', '')
                    if device_type in ['M', 'Q']:  # MOSFET or BJT
                        # Extract device name from node ID (format: "dev:M1")
                        device_name = node.replace('dev:', '')
                        transistor_devices.append(device_name)

            if not transistor_devices:
                print(f" ⚠ No transistors found, skipping")
                continue

            # Try standard .OP method first
            ac_params = None
            extraction_method = None
            try:
                ac_params = runner.extract_ac_params(netlist_text, transistor_devices)
                extraction_method = 'OP'
            except Exception as op_error:
                # Standard .OP method failed - try transient fallback
                print(f"\n        .OP method failed ({op_error}), falling back to transient...")
                ac_params = {}

                for device_name in transistor_devices:
                    try:
                        # Extract bias conditions from netlist
                        bias = extract_device_bias(netlist_text, device_name)

                        print(f"        {device_name}: trying transient @ Vgs={bias['vg_dc']:.2f}V, Vds={bias['vd_dc']:.2f}V...", end="")

                        # Use transient-based extraction
                        params_tran = runner.extract_ac_params_transient(
                            netlist_text,
                            device_name,
                            vg_dc=bias['vg_dc'],
                            vd_dc=bias['vd_dc'],
                            perturbation_mv=10.0,
                            freq_hz=1e6,
                            n_periods=5
                        )

                        ac_params[device_name] = {
                            'gm': params_tran['gm'],
                            'gds': params_tran['gds'],
                            'gmb': 0.0  # Not extracted by transient method
                        }
                        extraction_method = 'transient'
                        print(f" ✓ gm={params_tran['gm']:.2e}")

                    except Exception as tran_error:
                        print(f" ✗ {tran_error}")
                        # Set to zeros as last resort
                        ac_params[device_name] = {'gm': 0.0, 'gds': 0.0, 'gmb': 0.0}

            # Check if we got valid results
            if ac_params and any(p['gm'] != 0.0 for p in ac_params.values()):
                method_tag = f" ({extraction_method})" if extraction_method else ""
                print(f" ✓ {len(transistor_devices)} devices{method_tag}")

                small_signal_results.append({
                    'block': block,
                    'ac_params': ac_params,
                    'devices': transistor_devices,
                    'extraction_method': extraction_method
                })
            else:
                print(f" ⚠ All extractions failed, skipping block")

        except Exception as e:
            print(f" ✗ Failed: {e}")

    # Transient simulations for oscillator blocks
    transient_results = []
    if transient_plans:
        print(f"\n      Running {len(transient_plans)} transient simulations (oscillators)...")

        for i, tran_info in enumerate(transient_plans):
            block = tran_info['block']
            plan = tran_info['plan']
            block_name = block.get('name', f'block_{i}')

            print(f"      Oscillator {i+1}/{len(transient_plans)}: {block_name} "
                  f"(f_est={plan['expected_freq']/1e9:.2f} GHz, t={plan['tstop']*1e9:.1f}ns)", end="")

            try:
                # Run transient analysis (no input source modification for oscillators)
                results = runner.transient_analysis(netlist_text, plan)
                print(f" ✓ {len(results['time'])} points")

                transient_results.append({
                    'block': block,
                    'plan': plan,
                    'data': results
                })
            except Exception as e:
                print(f" ✗ Failed: {e}")

    # Step 5: Fit models (transfer functions for nonlinear, small-signal for linear)
    print("\n[5/7] Fitting models...")
    fitted_models = []

    # Build lookup for transient data by output variable name
    transient_by_output = {}
    for tran_result in transient_results:
        tran_data = tran_result['data']
        # Map each output variable to its transient data
        for var_name in tran_data.keys():
            if var_name != 'time':  # Skip the time axis
                transient_by_output[var_name] = {
                    'time': tran_data['time'],
                    'voltage': tran_data[var_name]
                }

    # Large-signal models (nonlinear blocks) + dynamic if transient available
    print("      Large-signal (DC + dynamic models):")
    for sim_result in simulation_results:
        plan = sim_result['plan']
        data = sim_result['data']
        plan_type = plan.get('type', 'dc_sweep')

        # Handle 2D sweeps
        if plan_type == 'dc_sweep_2d':
            sweep_var_1 = plan['sweep_var_1']
            sweep_var_2 = plan['sweep_var_2']
            x1 = data[sweep_var_1]
            x2 = data[sweep_var_2]

            for obs_var in plan['observe']:
                if obs_var not in data or obs_var in [sweep_var_1, sweep_var_2]:
                    continue

                z = data[obs_var]

                print(f"        {obs_var} = f({sweep_var_1}, {sweep_var_2})", end="")

                try:
                    from pipeline_ext.fit_transfer_function import fit_transfer_function_2d
                    model = fit_transfer_function_2d(x1, x2, z)

                    print(f" → {model['model_type']} ({model['intent']})")

                    fitted_models.append({
                        'input': [sweep_var_1, sweep_var_2],
                        'output': obs_var,
                        'model': model,
                        'data': {'x1': x1, 'x2': x2, 'z': z}
                    })

                except Exception as e:
                    print(f" → Failed: {e}")

            continue

        # Handle 1D sweeps (combine with transient if available)
        sweep_var = plan['sweep_var']
        x = data[sweep_var]

        for obs_var in plan['observe']:
            if obs_var not in data or obs_var == sweep_var:
                continue

            y = data[obs_var]

            print(f"        {obs_var} = f({sweep_var})", end="")

            try:
                # Try to find matching transient data
                # obs_var might be 'v(out)' or 'out' - try both
                obs_var_clean = obs_var.replace('v(', '').replace(')', '').replace('i(', '')

                transient_data = transient_by_output.get(obs_var_clean)

                # Use dynamic fitting if transient available
                if transient_data and len(transient_data['time']) > 0:
                    from pipeline_ext.fit_transfer_function import fit_dynamic_transfer_function

                    # Estimate step size from DC sweep range
                    input_step_size = abs(x[-1] - x[0]) if len(x) > 1 else 1.0

                    model = fit_dynamic_transfer_function(
                        dc_x=x,
                        dc_y=y,
                        transient_time=transient_data['time'],
                        transient_voltage=transient_data['voltage'],
                        input_step_size=input_step_size
                    )

                    # Display combined metrics
                    dc_gain = model['combined_params'].get('dc_gain')
                    bandwidth = model['combined_params'].get('bandwidth')
                    dc_gain_source = model['combined_params'].get('dc_gain_source')

                    # Show source for ring oscillators (DC from transient, not DC sweep)
                    source_tag = f"[{dc_gain_source}]" if dc_gain_source == 'transient' else ""

                    if dc_gain is not None and bandwidth is not None:
                        print(f" → dynamic (gain={dc_gain:.2f}{source_tag}, BW={bandwidth/1e6:.1f}MHz)")
                    elif dc_gain is not None:
                        print(f" → dynamic (gain={dc_gain:.2f}{source_tag}, DC-only)")
                    else:
                        print(f" → dynamic (no valid params)")

                else:
                    # DC-only fitting
                    model = fit_transfer_function(x, y)
                    print(f" → {model['model_type']} ({model['intent']})")

                fitted_models.append({
                    'input': sweep_var,
                    'output': obs_var,
                    'model': model,
                    'data': {'x': x, 'y': y}
                })

            except Exception as e:
                print(f" → Failed: {e}")

    # FALLBACK: If DC sweeps failed but we have transient data, fit from transient only
    if len(simulation_results) == 0 and len(transient_results) > 0:
        print("      Transient-only models (DC sweep failed):")
        for tran_result in transient_results:
            tran_data = tran_result['data']
            tran_plan = tran_result['plan']
            block = tran_result.get('block', {})

            # Extract input signals from block control axes
            control_axes = block.get('control_axes', set())
            if control_axes:
                # Use the block's control axes as inputs
                input_signals = list(control_axes)
                if len(input_signals) == 1:
                    input_name = input_signals[0]
                else:
                    input_name = input_signals  # Multi-input (2D)
            else:
                # No control axes found - this is likely an autonomous block (oscillator)
                # For oscillators, there's no meaningful input
                input_name = None  # Will generate oscillator model instead

            for var_name in tran_data.keys():
                if var_name == 'time':
                    continue  # Skip time axis

                if len(tran_data[var_name]) == 0:
                    continue  # Skip empty data

                print(f"        {var_name} (transient)", end="")

                try:
                    from pipeline_ext.fit_transfer_function import fit_dynamic_transfer_function

                    # Fit using ONLY transient data (no DC sweep)
                    model = fit_dynamic_transfer_function(
                        dc_x=None,  # No DC data available
                        dc_y=None,
                        transient_time=tran_data['time'],
                        transient_voltage=tran_data[var_name],
                        input_step_size=1.0  # Assume unit step
                    )

                    # Display metrics
                    dc_gain = model['combined_params'].get('dc_gain')
                    bandwidth = model['combined_params'].get('bandwidth')
                    dc_gain_source = model['combined_params'].get('dc_gain_source')

                    source_tag = f"[{dc_gain_source}]" if dc_gain_source == 'transient' else ""

                    if dc_gain is not None and bandwidth is not None:
                        print(f" → dynamic (gain={dc_gain:.2f}{source_tag}, BW={bandwidth/1e6:.1f}MHz)")
                    elif dc_gain is not None:
                        print(f" → dynamic (gain={dc_gain:.2f}{source_tag})")
                    else:
                        print(f" → insufficient data")
                        continue

                    # Add to fitted models with actual input name from block
                    fitted_models.append({
                        'input': input_name,  # Use actual control axes, not hardcoded 'transient'
                        'output': var_name,
                        'model': model,
                        'data': {
                            'time': tran_data['time'],
                            'voltage': tran_data[var_name]
                        }
                    })

                except Exception as e:
                    print(f" → Failed: {e}")

    # Structural linear models (passive-only, from AC sweep)
    print("      Structural linear (AC frequency response):")
    for linear_result in linear_ac_results:
        input_node = linear_result['input_node']
        ac_results = linear_result['ac_results']

        for output_node in linear_result['output_nodes']:
            if output_node not in ac_results:
                continue

            freq = ac_results['frequency']
            mag = ac_results[output_node]['magnitude']
            phase = ac_results[output_node]['phase']

            print(f"        {output_node} = H(s) * {input_node}", end="")

            # Create linear frequency-domain model
            # Store frequency response (will be fit to transfer function in next step)
            model = {
                'model_type': 'linear_ac',
                'intent': 'linear',
                'frequency': freq,
                'magnitude': mag,
                'phase': phase,
                'dc_gain': mag[0] if len(mag) > 0 else 1.0,  # Low-frequency gain
            }

            fitted_models.append({
                'input': input_node,
                'output': output_node,
                'model': model,
                'data': {
                    'frequency': freq,
                    'magnitude': mag,
                    'phase': phase
                }
            })

            print(f" → DC gain: {model['dc_gain']:.3f}")

    # Small-signal models (linear blocks)
    print("      Small-signal (linear blocks):")
    for ss_result in small_signal_results:
        extraction_method = ss_result.get('extraction_method', 'OP')
        method_tag = f" [{extraction_method}]" if extraction_method == 'transient' else ""

        for device_name, ac_params in ss_result['ac_params'].items():
            print(f"        {device_name}: gm={ac_params['gm']:.2e}, gds={ac_params['gds']:.2e}{method_tag}")

            # Create small-signal model
            model = extract_small_signal_model(ac_params)
            model['model_type'] = 'small_signal'  # Add model_type for Verilog generator
            model['intent'] = 'linear'
            model['extraction_method'] = extraction_method  # Track which method was used

            fitted_models.append({
                'input': device_name,  # Device name
                'output': 'small_signal',
                'model': model,
                'data': {},
                'terminals': {}  # Will be populated by Verilog generator
            })

    # Oscillator models (transient simulation)
    if transient_results:
        print("      Oscillator models (dynamic blocks):")
        from pipeline_ext.fit_transfer_function import fit_oscillator_model

        for tran_result in transient_results:
            block = tran_result['block']
            data = tran_result['data']
            outputs = list(block.get('outputs', set()))

            if not outputs:
                continue

            # Analyze each output
            for output in outputs:
                output_name = output.replace('net:', '')

                # Skip ground nodes
                if output_name.lower() in ['0', 'gnd']:
                    continue

                # Get waveform data for this output
                if output_name not in data:
                    continue

                time = data['time']
                voltage = data[output_name]

                # Fit oscillator model
                model = fit_oscillator_model(time, voltage)

                if model['model_type'] == 'oscillator':
                    freq_ghz = model['params']['frequency'] / 1e9
                    amp = model['params']['amplitude']
                    waveform = model.get('waveform', 'unknown')

                    print(f"        {output_name}: {waveform} @ {freq_ghz:.2f} GHz, amp={amp:.3f}V")

                    fitted_models.append({
                        'input': None,  # No input for autonomous oscillators
                        'output': output_name,
                        'model': model,
                        'data': {'time': time, 'voltage': voltage}
                    })

    # Step 6: Generate Verilog-AMS
    print("\n[6/7] Generating Verilog-AMS code...")
    generator = VerilogAMSGenerator()

    for fitted_model in fitted_models:
        module_name = f"{fitted_model['output']}_vs_{fitted_model['input']}"
        module_name = module_name.replace(':', '_')

        print(f"      Module: {module_name}")

        code = generator.generate_module(fitted_model, module_name)

        # Show snippet
        for line in code.split('\n'):
            if 'module' in line and '(' in line:
                print(f"        {line.strip()}")
            elif 'intent:' in line.lower():
                print(f"        {line.strip()}")

    # Step 7: Check equivalence using OSDI (optional)
    equivalence_results = []

    if OSDI_AVAILABLE:
        print("\n[7/8] Checking equivalence with OSDI...")
        osdi_checker = OSDIEquivalenceChecker(abs_tol=0.01, rel_tol=0.05)
    else:
        print("\n[7/8] Skipping OSDI equivalence check (OpenVAF not available)...")
        print("      Install OpenVAF for equivalence validation")

    for i, fitted_model in enumerate(fitted_models):
        # Handle both 1D and 2D models, and oscillators (no input)
        is_2d = isinstance(fitted_model['input'], list)
        is_oscillator = fitted_model['input'] is None

        if is_oscillator:
            # Oscillators have no input (autonomous)
            module_name = f"{fitted_model['output']}_oscillator"
            input_names = []
        elif is_2d:
            input_str = '_'.join(fitted_model['input'])
            module_name = f"{fitted_model['output']}_vs_{input_str}"
            input_names = [inp.replace('net:', '') for inp in fitted_model['input']]
        else:
            module_name = f"{fitted_model['output']}_vs_{fitted_model['input']}"
            input_names = [fitted_model['input'].replace('net:', '')]

        module_name = module_name.replace(':', '_').replace('net:', '')

        # Get the generated code
        code = generator.generate_module(fitted_model, module_name)

        # Extract output name
        output_name = fitted_model['output'].replace('net:', '')

        # Check if this is a small-signal model
        model_type = fitted_model.get('model', {}).get('model_type', '')
        is_small_signal = (model_type == 'small_signal' or
                          fitted_model['output'] == 'small_signal')

        # Determine validation mode based on what data is available in the model
        model_data = fitted_model.get('data', {})
        has_dc_data = 'x' in model_data or 'x1' in model_data  # DC sweep data
        has_transient_data = 'time' in model_data or 'voltage' in model_data  # Transient data

        # Use transient mode if:
        # 1. Model has transient data but no DC data (transient-only fallback)
        # 2. Model has both but was built from transient (check model type)
        # 3. Model is an oscillator (autonomous, no DC sweep possible)
        model_type = fitted_model.get('model', {}).get('model_type', '')
        is_oscillator = model_type == 'oscillator'

        if has_transient_data and not has_dc_data:
            validation_mode = 'transient'
        elif is_oscillator:
            validation_mode = 'transient'
        elif has_dc_data:
            validation_mode = 'auto'  # OSDI will try DC first
        else:
            validation_mode = 'auto'  # Let OSDI decide

        # Only run OSDI check if available and not a small-signal model
        if OSDI_AVAILABLE:
            if is_small_signal:
                # Small-signal models represent linearized device behavior
                # around a DC operating point. They can't be validated standalone
                # with DC sweeps - they need to be embedded in a complete circuit.
                # Instead, we validate the extracted parameters (gm, gds).
                ac_params = fitted_model.get('model', {})
                gm = ac_params.get('gm', 0)
                gds = ac_params.get('gds', 0)
                print(f"      ○ {module_name}: small-signal model " +
                      f"(gm={gm:.2e} S, gds={gds:.2e} S) - parameter validation only")
            else:
                try:
                    # Use oscillator-specific checker for oscillator models
                    if is_oscillator and OSCILLATOR_CHECKER_AVAILABLE:
                        # Use frequency-domain oscillator equivalence checker
                        import numpy as np

                        # Run SPICE transient simulation
                        spice_data = osdi_checker._run_transient_spice(
                            netlist_text, [output_name], 30e-9, 100e-12
                        )

                        if spice_data and output_name in spice_data:
                            spice_time = np.array(spice_data['time'])
                            spice_voltage = np.array(spice_data[output_name])

                            # Extract parameters from VA model
                            import re
                            freq_match = re.search(r'parameter real frequency = ([0-9.e+-]+)', code)
                            amp_match = re.search(r'parameter real amplitude = ([0-9.e+-]+)', code)
                            offset_match = re.search(r'parameter real offset = ([0-9.e+-]+)', code)

                            if freq_match and amp_match and offset_match:
                                expected_freq = float(freq_match.group(1))
                                expected_amp = float(amp_match.group(1))
                                expected_offset = float(offset_match.group(1))

                                # Generate VA model waveform
                                vams_voltage = expected_offset + expected_amp * np.sin(
                                    2 * np.pi * expected_freq * spice_time
                                )

                                # Check oscillator equivalence with frequency-domain metrics
                                osc_result = check_oscillator_equivalence(
                                    spice_time, spice_voltage,
                                    spice_time, vams_voltage,
                                    freq_tol=0.05,  # 5% frequency tolerance
                                    amp_tol=0.10,   # 10% amplitude tolerance
                                    offset_tol=0.5  # 500mV offset tolerance (relaxed for context-dependent DC bias)
                                )

                                # Create compatible result object for reporting
                                class OscEquivResult:
                                    def __init__(self, osc_res):
                                        self.passed = osc_res.passed
                                        self.max_absolute_error = osc_res.frequency_error
                                        self.correlation = 1.0 - (osc_res.amplitude_error_pct / 100.0)

                                result = OscEquivResult(osc_result)
                                equivalence_results.append({
                                    'module': module_name,
                                    'result': result,
                                    'oscillator_metrics': {
                                        'freq_error_pct': osc_result.frequency_error_pct,
                                        'amp_error_pct': osc_result.amplitude_error_pct,
                                        'offset_error': osc_result.offset_error
                                    }
                                })

                                status = "✓" if result.passed else "✗"
                                print(f"      {status} 🔄 {module_name} (oscillator, freq-domain): " +
                                      f"freq_err={osc_result.frequency_error_pct:.2f}%, " +
                                      f"amp_err={osc_result.amplitude_error_pct:.2f}%")
                            else:
                                print(f"      ⚠ {module_name}: could not extract oscillator parameters from VA model")
                        else:
                            print(f"      ⚠ {module_name}: oscillator SPICE simulation failed")
                    else:
                        # Use regular OSDI checker for non-oscillator models
                        mode_desc = f" (using {validation_mode} mode)" if validation_mode == 'transient' else ""

                        result = osdi_checker.check_equivalence(
                            netlist_text, code, module_name,
                            input_names=input_names,
                            output_names=[output_name],
                            n_test_points=20,
                            mode=validation_mode
                        )
                        equivalence_results.append({
                            'module': module_name,
                            'result': result
                        })

                        # Add mode indicator to status
                        mode_indicator = '⏱' if validation_mode == 'transient' else ''
                        status = "✓" if result.passed else "✗"

                        # Handle None values from skipped checks
                        if result.max_absolute_error is not None and result.correlation is not None:
                            print(f"      {status} {mode_indicator} {module_name}{mode_desc}: " +
                                  f"max_err={result.max_absolute_error:.2e}, " +
                                  f"corr={result.correlation:.3f}")
                        else:
                            print(f"      {status} {mode_indicator} {module_name}{mode_desc}: validation skipped")
                except Exception as e:
                    print(f"      ⚠ {module_name}: equivalence check failed ({e})")

    # Step 8: Save files
    print("\n[8/8] Saving files to disk...")
    saved_files = generator.save_all(output_dir)

    print(f"      Saved {len(saved_files)} files to {output_dir}/")
    for f in saved_files:
        print(f"        - {f.name}")

    print("\n" + "="*70)
    print(" PIPELINE COMPLETE!")
    print("="*70)
    print(f"\n  Blocks analyzed:        {len(blocks)}")
    print(f"    Structural linear:    {len(structural_linear_blocks)}")
    print(f"    Small-signal linear:  {len(small_signal_blocks)}")
    print(f"    Nonlinear:            {len(nonlinear_blocks)}")
    print(f"  DC sweeps run:          {len(simulation_results)}")
    print(f"  AC sweeps run:          {len(linear_ac_results)}")
    print(f"  Small-signal extracts:  {len(small_signal_results)}")
    print(f"  Models fitted:          {len(fitted_models)}")
    print(f"  Verilog-AMS modules:    {len([f for f in saved_files if str(f).endswith('.va')])}")

    # Equivalence check summary
    if equivalence_results:
        passed = sum(1 for er in equivalence_results if er['result'].passed)
        failed = len(equivalence_results) - passed
        print(f"  Equivalence checks:     {len(equivalence_results)} total")
        print(f"    Passed:               {passed}")
        if failed > 0:
            print(f"    Failed:               {failed}")

    return saved_files


if __name__ == "__main__":
    # Test with common source amplifier
    test_netlist = """
* Common source amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

    print("\nTest Circuit: Common Source Amplifier")
    print(test_netlist)

    saved_files = spice_to_verilog_ams(test_netlist, '/home/vrajeshprakhya/circuit_preprocess')

    # Show generated Verilog-AMS
    print("\n" + "="*70)
    print(" GENERATED VERILOG-AMS CODE")
    print("="*70)

    for f in saved_files:
        if str(f).endswith('.va'):
            print(f"\n{'='*70}")
            print(f" File: {f.name}")
            print("="*70)
            with open(f, 'r') as file:
                print(file.read())
