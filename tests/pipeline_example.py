#!/usr/bin/env python3
"""
pipeline_example.py

End-to-end example showing how to use the complete pipeline:
1. Parse SPICE netlist
2. Analyze circuit structure
3. Plan simulations
4. Run ngspice
5. Fit transfer functions
6. (Future: Generate Verilog-AMS)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from graph_builder import parse_spice_netlist, build_bipartite_graph
from circuit_analyzer import analyze_blocks
from simulation_planner import SimulationPlanner
from ngspice_runner import NgspiceRunner, NgspiceError
from fit_transfer_function_dc_sweep import fit_transfer_function

import numpy as np
from pprint import pprint


def run_pipeline(netlist_text):
    """
    Run complete pipeline on a SPICE netlist

    Args:
        netlist_text: SPICE netlist as string

    Returns:
        list: Fitted models for each block
    """
    print("=" * 60)
    print("STEP 1: Parse SPICE netlist")
    print("=" * 60)

    devices = parse_spice_netlist(netlist_text)
    print(f"Found {len(devices)} devices")

    print("\n" + "=" * 60)
    print("STEP 2: Build bipartite graph")
    print("=" * 60)

    graph = build_bipartite_graph(devices)
    print(f"Graph has {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

    print("\n" + "=" * 60)
    print("STEP 3: Analyze circuit structure")
    print("=" * 60)

    blocks = analyze_blocks(graph)
    print(f"Found {len(blocks)} blocks\n")

    for block in blocks:
        print(f"Block {block['block_id']}:")
        print(f"  Inputs: {block['inputs']}")
        print(f"  Outputs: {block['outputs']}")
        print(f"  Simulation axes: {block['simulation_axes']}")
        print(f"  Linear intent: {block['linear_intent']}")
        print()

    print("=" * 60)
    print("STEP 4: Plan simulations")
    print("=" * 60)

    # Get constant nets for planner
    from circuit_analyzer import find_constant_nets
    constant_nets = find_constant_nets(graph)

    planner = SimulationPlanner(graph, constant_nets)

    all_sweep_plans = []
    for block in blocks:
        sweep_plans = planner.plan_dc_sweep(block)
        all_sweep_plans.extend(sweep_plans)

        if sweep_plans:
            print(f"\nBlock {block['block_id']} sweep plans:")
            for plan in sweep_plans:
                print(f"  Sweep {plan['sweep_var']}: "
                      f"{plan['start']:.2f}V → {plan['stop']:.2f}V "
                      f"(step={plan['step']:.4f}V)")
                print(f"    Observe: {plan['observe']}")

    print("\n" + "=" * 60)
    print("STEP 5: Run ngspice simulations")
    print("=" * 60)

    runner = NgspiceRunner()
    simulation_results = []

    for i, plan in enumerate(all_sweep_plans):
        print(f"\nRunning sweep {i+1}/{len(all_sweep_plans)}: {plan['sweep_var']}")

        try:
            results = runner.dc_sweep(netlist_text, plan)

            print(f"  Success! Got {len(results[plan['sweep_var']])} data points")

            # Store results with plan
            simulation_results.append({
                'plan': plan,
                'data': results
            })

        except NgspiceError as e:
            print(f"  FAILED: {e}")

    print("\n" + "=" * 60)
    print("STEP 6: Fit transfer functions")
    print("=" * 60)

    fitted_models = []

    for sim_result in simulation_results:
        plan = sim_result['plan']
        data = sim_result['data']

        sweep_var = plan['sweep_var']
        x = data[sweep_var]

        # Fit for each observed output
        for obs_var in plan['observe']:
            if obs_var not in data or obs_var == sweep_var:
                continue

            y = data[obs_var]

            print(f"\nFitting {obs_var} vs {sweep_var}:")
            print(f"  Input range: [{x.min():.3f}, {x.max():.3f}]")
            print(f"  Output range: [{y.min():.3e}, {y.max():.3e}]")

            try:
                model = fit_transfer_function(x, y)

                print(f"  Intent: {model['intent']}")
                print(f"  Model type: {model['model_type']}")

                if model['model_type'] == 'analytic':
                    print(f"  Regions: {len(model['regions'])}")
                    if 'fit_quality' in model:
                        print(f"  Fit quality:")
                        for metric, value in model['fit_quality'].items():
                            print(f"    {metric}: {value:.6f}")

                fitted_models.append({
                    'input': sweep_var,
                    'output': obs_var,
                    'model': model,
                    'data': {'x': x, 'y': y}
                })

            except Exception as e:
                print(f"  Fit FAILED: {e}")

    print("\n" + "=" * 60)
    print("STEP 7: Summary")
    print("=" * 60)

    print(f"\nPipeline complete!")
    print(f"  Blocks analyzed: {len(blocks)}")
    print(f"  Simulations run: {len(simulation_results)}")
    print(f"  Models fitted: {len(fitted_models)}")

    return fitted_models


if __name__ == "__main__":
    # Test with simple NMOS circuit
    test_netlist = """
* Simple NMOS test circuit
M1 vd vg 0 0 NMOS W=1u L=1u
VDD vd 0 DC 1.8V
Vin vg 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

    print("Testing pipeline with simple NMOS circuit\n")
    models = run_pipeline(test_netlist)

    # Optionally: visualize results
    if models and False:  # Set to True to enable plotting
        import matplotlib.pyplot as plt

        for i, fitted_model in enumerate(models):
            x = fitted_model['data']['x']
            y = fitted_model['data']['y']

            plt.figure(figsize=(10, 6))
            plt.plot(x, y, 'o-', label='Simulation data')
            plt.xlabel(f"{fitted_model['input']} (V)")
            plt.ylabel(f"{fitted_model['output']} (V)")
            plt.title(f"Transfer function: {fitted_model['output']} vs {fitted_model['input']}")
            plt.grid(True)
            plt.legend()
            plt.savefig(f"model_{i}.png")
            print(f"Saved plot to model_{i}.png")
