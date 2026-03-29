#!/usr/bin/env python3
"""
Test the FIXED SerDes circuit with hybrid ensemble pipeline.
This should converge properly with the added startup resistors and nodesets.
"""
from hybrid_ensemble import ensemble_pipeline
import time

print("=" * 80)
print("TESTING FIXED SERDES CIRCUIT WITH HYBRID ENSEMBLE PIPELINE")
print("=" * 80)
print()
print("Fixed circuit includes:")
print("  ✓ Startup resistors in differential pairs")
print("  ✓ .nodeset directives for all critical nodes")
print("  ✓ Convergence options (gmin, abstol, itl)")
print("  ✓ UIC flag for transient (skip DC operating point)")
print()

# Read the fixed netlist
with open('serdes_top_fixed.cir', 'r') as f:
    fixed_netlist = f.read()

print(f"Netlist size: {len(fixed_netlist)} chars")
print()

# Run the hybrid ensemble
print("Running hybrid ensemble pipeline...")
print("This will:")
print("  1. Run AI pipeline (with transient on all blocks)")
print("  2. Run Programmatic pipeline (with DC + transient dynamic fitting)")
print("  3. Compare NRMSE on independent test data")
print("  4. Select best-performing model")
print()

start_time = time.time()

result = ensemble_pipeline(
    netlist_text=fixed_netlist,
    output_dir='./output_serdes_fixed',
    cache=False,  # Disable cache for fresh test
    parallel=True
)

elapsed = time.time() - start_time

print()
print("=" * 80)
print("HYBRID ENSEMBLE RESULTS")
print("=" * 80)
print(f"Total time: {elapsed:.2f}s")
print()

if result:
    print(f"Winner: {result.get('winner', 'Unknown')}")
    print(f"AI Pipeline NRMSE: {result.get('ai_nrmse', 'N/A')}")
    print(f"Programmatic Pipeline NRMSE: {result.get('prog_nrmse', 'N/A')}")
    print(f"Improvement: {result.get('improvement', 'N/A')}%")
    print()

    # Check if we got valid models with dynamic fitting
    if result['winner'] == 'programmatic':
        print("✓ Programmatic pipeline won - checking for dynamic models...")
        import os
        if os.path.exists('./output_serdes_fixed/programmatic'):
            va_files = [f for f in os.listdir('./output_serdes_fixed/programmatic')
                       if f.endswith('.va')]
            print(f"  Generated {len(va_files)} Verilog-AMS files")

            # Check for dynamic parameters in generated files
            for va_file in va_files:
                with open(f'./output_serdes_fixed/programmatic/{va_file}', 'r') as f:
                    content = f.read()
                    if 'bandwidth' in content.lower():
                        print(f"  ✓ {va_file} contains bandwidth parameter (dynamic model!)")
                    if 'time_constant' in content.lower():
                        print(f"  ✓ {va_file} contains time_constant parameter (dynamic model!)")
                    if 'dc_gain' in content.lower():
                        print(f"  ✓ {va_file} contains dc_gain parameter")

    elif result['winner'] == 'ai':
        print("✓ AI pipeline won")

    elif result['winner'] == 'both_failed':
        print("⚠ Both pipelines failed")
else:
    print("⚠ Hybrid ensemble returned no result")

print()
print("=" * 80)
