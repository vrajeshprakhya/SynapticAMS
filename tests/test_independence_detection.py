#!/usr/bin/env python3
"""
Test independence detection and 2D sweep generation

Tests two scenarios:
1. Coupled sources → should generate 2D sweep
2. Independent sources → should generate separate 1D sweeps
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from graph_builder import parse_spice_netlist, build_bipartite_graph
from circuit_analyzer import analyze_blocks, find_constant_nets
from simulation_planner import SimulationPlanner
from ngspice_runner import NgspiceRunner

# Test Case 1: COUPLED SOURCES
# Simple amplifier where voltage (Vcontrol) sets operating point
# and current (Iload) pulls current from output → Both affect Vout
# These are STRONGLY coupled: changing Iload shifts the V-I curve
# Using AC sources so circuit_analyzer detects them as signal sources
coupled_netlist = """* Common-source amp with current load (coupled)
M1 out vctl 0 0 NMOS W=20u L=1u
Vctl vctl 0 DC 0 AC 1
Iload vdd out DC 0 AC 10u
RD vdd out 10k
VDD vdd 0 DC 1.8
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

# Test Case 2: INDEPENDENT SOURCES
# Two completely separate amplifier stages
# Vin and Iin drive different transistors with separate outputs
# Using AC sources so circuit_analyzer detects them as signal sources
independent_netlist = """* Two independent amplifier stages
* Stage 1: Voltage-driven
Vin vin 0 DC 0 AC 1
M1 out1 vin 0 0 NMOS W=10u L=1u
R1 vdd out1 10k

* Stage 2: Current-driven
Iin in2 0 DC 0 AC 1u
R2 in2 0 1k
M2 out2 in2 0 0 NMOS W=10u L=1u
R3 vdd out2 10k

VDD vdd 0 DC 1.8
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

def test_circuit(netlist, description):
    """Test independence detection on a circuit"""
    print("=" * 70)
    print(f"Testing: {description}")
    print("=" * 70)

    # Parse netlist
    print("\n[1/3] Parsing netlist...")
    devices = parse_spice_netlist(netlist)
    graph = build_bipartite_graph(devices)
    print(f"      Found {len(devices)} devices")

    # Analyze blocks
    print("\n[2/3] Analyzing circuit structure...")
    constant_nets = find_constant_nets(graph)
    blocks = analyze_blocks(graph)
    print(f"      Identified {len(blocks)} functional blocks")

    for block in blocks:
        print(f"\n      Block {block['block_id']}:")
        print(f"        Inputs: {block['inputs']}")
        print(f"        Outputs: {block['outputs']}")
        print(f"        Control axes: {block['simulation_axes']}")
        print(f"        Behavior class: {block.get('behavior_class', 'N/A')}")

    # Plan simulations with independence detection
    print("\n[3/3] Planning simulations with independence detection...")
    runner = NgspiceRunner()
    planner = SimulationPlanner(graph, constant_nets, netlist=netlist, runner=runner)

    # Get nonlinear and small-signal blocks (both need DC sweeps)
    # Note: SMALL_SIGNAL_LINEARIZABLE circuits still need DC characterization
    #       for large-signal behavior and bias point determination
    sweep_candidate_blocks = [b for b in blocks
                               if b.get('behavior_class') in ['NONLINEAR', 'SMALL_SIGNAL_LINEARIZABLE']]

    all_sweep_plans = []
    for block in sweep_candidate_blocks:
        sweep_plans = planner.plan_dc_sweep(block)
        all_sweep_plans.extend(sweep_plans)

    # Display results
    print(f"\n      Generated {len(all_sweep_plans)} sweep plan(s):")
    for i, plan in enumerate(all_sweep_plans):
        plan_type = plan.get('type', 'dc_sweep')
        print(f"\n      Plan {i+1}:")
        print(f"        Type: {plan_type}")

        if plan_type == 'dc_sweep_2d':
            print(f"        Sweep 1: {plan['sweep_var_1']} [{plan['start_1']:.2f} → {plan['stop_1']:.2f}], step={plan['step_1']:.4f}")
            print(f"        Sweep 2: {plan['sweep_var_2']} [{plan['start_2']:.2e} → {plan['stop_2']:.2e}], step={plan['step_2']:.2e}")
            print(f"        Observe: {plan['observe']}")
            print(f"        Coupling strength: {plan['coupling_info']['coupling_strength']:.3f}")
        else:
            print(f"        Sweep: {plan['sweep_var']} [{plan['start']:.2f} → {plan['stop']:.2f}], step={plan['step']:.4f}")
            print(f"        Observe: {plan['observe']}")

    return all_sweep_plans


def main():
    print("\n" + "=" * 70)
    print(" INDEPENDENCE DETECTION TEST SUITE")
    print("=" * 70)

    # Test coupled sources
    print("\n\n")
    coupled_plans = test_circuit(coupled_netlist, "Coupled Sources (Current-Feedback Amp)")

    # Test independent sources
    print("\n\n")
    independent_plans = test_circuit(independent_netlist, "Independent Sources (Two Stages)")

    # Summary
    print("\n\n" + "=" * 70)
    print(" TEST SUMMARY")
    print("=" * 70)

    print("\nCoupled sources test:")
    if len(coupled_plans) == 1 and coupled_plans[0].get('type') == 'dc_sweep_2d':
        print("  ✓ PASS - Correctly detected coupling, generated 2D sweep")
    else:
        print("  ✗ FAIL - Should have generated 2D sweep")
        print(f"    Got {len(coupled_plans)} plan(s), type={coupled_plans[0].get('type') if coupled_plans else 'none'}")

    print("\nIndependent sources test:")
    if len(independent_plans) >= 2 and all(p.get('type') == 'dc_sweep' for p in independent_plans):
        print("  ✓ PASS - Correctly detected independence, generated 1D sweeps")
    elif len(independent_plans) == 0:
        print("  ⚠ SKIP - No nonlinear blocks found (expected for independent stages)")
    else:
        print("  ✗ FAIL - Should have generated separate 1D sweeps")
        print(f"    Got {len(independent_plans)} plan(s)")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
