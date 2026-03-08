#!/usr/bin/env python3
"""
Debug: See exactly what ngspice commands are being generated
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from graph_builder import parse_spice_netlist, build_bipartite_graph
from circuit_analyzer import analyze_blocks
from simulation_planner import SimulationPlanner
from circuit_analyzer import find_constant_nets

test_netlist = """
* Resistive Feedback Inverter Test
.model nshort nmos (level=1 vto=0.7 kp=200u lambda=0.02 gamma=0.4)
.model pshort pmos (level=1 vto=-0.7 kp=100u lambda=0.02 gamma=0.4)

Vdd vdd 0 DC 1.8V
Vin inp 0 DC 0.9V AC 1

MN0 out inp 0 0 nshort w=5u l=0.15u
MN1 out inp 0 0 nshort w=5u l=0.15u
MP0 out inp vdd vdd pshort w=5u l=0.15u
MP1 out inp vdd vdd pshort w=5u l=0.15u
MPfb1 out out net06 vdd pshort w=0.55u l=8u
MPfb0 net06 net06 inp vdd pshort w=0.55u l=8u

Cout out 0 10f
"""

print("="*70)
print(" DEBUG: Analyzing receiver circuit")
print("="*70)

# Step 1: Parse
devices = parse_spice_netlist(test_netlist)
graph = build_bipartite_graph(devices)
print(f"\n1. Parsed {len(devices)} devices")

# Step 2: Analyze
blocks = analyze_blocks(graph)
print(f"\n2. Found {len(blocks)} blocks")

for block in blocks:
    print(f"\n   Block {block['block_id']}:")
    print(f"   - Behavior: {block['behavior_class']}")
    print(f"   - Inputs: {block['inputs']}")
    print(f"   - Outputs: {block['outputs']}")
    print(f"   - Control axes: {block['simulation_axes']}")

    # Filter out ground
    ground_nodes = {'net:0', '0', 'net:gnd', 'gnd'}
    filtered_axes = block['simulation_axes'] - ground_nodes
    print(f"   - Control axes (filtered): {filtered_axes}")

# Step 3: Plan simulations
constant_nets = find_constant_nets(graph)
planner = SimulationPlanner(graph, constant_nets)

print(f"\n3. Planning DC sweeps...")

for block in blocks:
    # Filter ground BEFORE planning
    ground_nodes = {'net:0', '0', 'net:gnd', 'gnd'}
    block_filtered = block.copy()
    block_filtered['simulation_axes'] = block['simulation_axes'] - ground_nodes

    sweep_plans = planner.plan_dc_sweep(block_filtered)

    print(f"\n   Block {block['block_id']}: {len(sweep_plans)} sweep plans")

    for i, plan in enumerate(sweep_plans):
        print(f"\n   Plan {i+1}:")
        print(f"   - Sweep variable: {plan['sweep_var']}")
        print(f"   - Range: {plan['start']:.2f}V → {plan['stop']:.2f}V")
        print(f"   - Step: {plan['step']:.3f}V")
        print(f"   - Observe: {plan['observe']}")

# Step 4: Test actual ngspice command
print("\n" + "="*70)
print(" Testing ngspice DC sweep")
print("="*70)

if sweep_plans:
    from ngspice_runner import NgspiceRunner
    runner = NgspiceRunner()

    plan = sweep_plans[0]
    print(f"\nSweeping {plan['sweep_var']} from {plan['start']}V to {plan['stop']}V")
    print(f"Observing: {plan['observe']}")

    try:
        results = runner.dc_sweep(test_netlist, plan)
        print(f"\n✓ Success! Got {len(results.get(plan['sweep_var'], []))} data points")

        # Show first few points
        sweep_var = plan['sweep_var']
        if sweep_var in results:
            print(f"\nFirst 5 points of {sweep_var}:")
            print(results[sweep_var][:5])

        for obs in plan['observe']:
            if obs in results:
                print(f"\nFirst 5 points of {obs}:")
                print(results[obs][:5])

    except Exception as e:
        print(f"\n✗ Failed: {e}")
        import traceback
        traceback.print_exc()
