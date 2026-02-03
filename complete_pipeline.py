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
    planner = SimulationPlanner(graph, constant_nets)

    # Separate blocks by intent
    linear_blocks = [b for b in blocks if b.get('linear_intent', False)]
    nonlinear_blocks = [b for b in blocks if not b.get('linear_intent', False)]

    print(f"      Linear blocks: {len(linear_blocks)}")
    print(f"      Nonlinear blocks: {len(nonlinear_blocks)}")

    # Plan DC sweeps only for nonlinear blocks
    all_sweep_plans = []
    for block in nonlinear_blocks:
        sweep_plans = planner.plan_dc_sweep(block)
        all_sweep_plans.extend(sweep_plans)

    print(f"      Generated {len(all_sweep_plans)} DC sweep plans (nonlinear blocks)")

    # Step 4: Run ngspice simulations
    print("\n[4/7] Running ngspice simulations...")
    runner = NgspiceRunner()
    simulation_results = []
    small_signal_results = []

    # DC sweeps for nonlinear blocks
    for i, plan in enumerate(all_sweep_plans):
        sweep_var = plan['sweep_var']
        print(f"      DC Sweep {i+1}/{len(all_sweep_plans)}: {sweep_var} "
              f"[{plan['start']:.2f}V → {plan['stop']:.2f}V]", end="")

        try:
            results = runner.dc_sweep(netlist_text, plan)
            print(f" ✓ {len(results[sweep_var])} points")

            simulation_results.append({
                'plan': plan,
                'data': results
            })
        except Exception as e:
            print(f" ✗ Failed: {e}")

    # DC operating point + AC parameter extraction for linear blocks
    for i, block in enumerate(linear_blocks):
        print(f"      Linear block {i+1}/{len(linear_blocks)}: extracting AC params...", end="")

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

    # Step 7: Save files
    print("\n[7/7] Saving files to disk...")
    saved_files = generator.save_all(output_dir)

    print(f"      Saved {len(saved_files)} files to {output_dir}/")
    for f in saved_files:
        print(f"        - {f.name}")

    print("\n" + "="*70)
    print(" PIPELINE COMPLETE!")
    print("="*70)
    print(f"\n  Blocks analyzed:        {len(blocks)}")
    print(f"    Linear blocks:        {len(linear_blocks)}")
    print(f"    Nonlinear blocks:     {len(nonlinear_blocks)}")
    print(f"  DC sweeps run:          {len(simulation_results)}")
    print(f"  Small-signal extracts:  {len(small_signal_results)}")
    print(f"  Models fitted:          {len(fitted_models)}")
    print(f"  Verilog-AMS modules:    {len([f for f in saved_files if str(f).endswith('.va')])}")

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
