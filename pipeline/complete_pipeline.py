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

from graph_builder import parse_spice_netlist, build_bipartite_graph
from circuit_analyzer import analyze_blocks
from simulation_planner import SimulationPlanner
from ngspice_runner import NgspiceRunner
from fit_transfer_function_dc_sweep import fit_transfer_function
from verilog_ams_generator import VerilogAMSGenerator
from extract_small_signal_model import extract_small_signal_model
from equivalence_checker import EquivalenceChecker
from equivalence_checker_osdi import OSDIEquivalenceChecker

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

    # Step 1: Parse netlist
    print("\n[1/7] Parsing SPICE netlist...")
    devices = parse_spice_netlist(netlist_text)
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
    from circuit_analyzer import find_constant_nets
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

    print(f"      Generated {len(all_sweep_plans)} DC sweep plans (small-signal + nonlinear blocks)")

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

            # Extract AC parameters
            ac_params = runner.extract_ac_params(netlist_text, transistor_devices)
            print(f" ✓ {len(transistor_devices)} devices")

            small_signal_results.append({
                'block': block,
                'ac_params': ac_params,
                'devices': transistor_devices
            })

        except Exception as e:
            print(f" ✗ Failed: {e}")

    # Step 5: Fit models (transfer functions for nonlinear, small-signal for linear)
    print("\n[5/7] Fitting models...")
    fitted_models = []

    # Large-signal models (nonlinear blocks)
    print("      Large-signal (nonlinear blocks):")
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
                    from fit_transfer_function_dc_sweep import fit_transfer_function_2d
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

        # Handle 1D sweeps
        sweep_var = plan['sweep_var']
        x = data[sweep_var]

        for obs_var in plan['observe']:
            if obs_var not in data or obs_var == sweep_var:
                continue

            y = data[obs_var]

            print(f"        {obs_var} = f({sweep_var})", end="")

            try:
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
        for device_name, ac_params in ss_result['ac_params'].items():
            print(f"        {device_name}: gm={ac_params['gm']:.2e}, gds={ac_params['gds']:.2e}")

            # Create small-signal model
            model = extract_small_signal_model(ac_params)
            model['model_type'] = 'small_signal'  # Add model_type for Verilog generator
            model['intent'] = 'linear'

            fitted_models.append({
                'input': device_name,  # Device name
                'output': 'small_signal',
                'model': model,
                'data': {},
                'terminals': {}  # Will be populated by Verilog generator
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

    # Step 7: Check equivalence using OSDI
    print("\n[7/8] Checking equivalence with OSDI...")
    osdi_checker = OSDIEquivalenceChecker(abs_tol=0.01, rel_tol=0.05)
    equivalence_results = []

    for i, fitted_model in enumerate(fitted_models):
        # Handle both 1D and 2D models
        is_2d = isinstance(fitted_model['input'], list)

        if is_2d:
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

        try:
            result = osdi_checker.check_equivalence(
                netlist_text, code, module_name,
                input_names=input_names,
                output_names=[output_name],
                n_test_points=20
            )
            equivalence_results.append({
                'module': module_name,
                'result': result
            })
            status = "✓" if result.passed else "✗"
            print(f"      {status} {module_name}: " +
                  f"max_err={result.max_absolute_error:.2e}, " +
                  f"corr={result.correlation:.3f}, " +
                  f"n={result.n_points}")
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
