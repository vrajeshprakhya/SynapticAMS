#!/usr/bin/env python3
"""
Test hybrid ensemble with NMOS DC sweep example
"""

from pathlib import Path
from hybrid_ensemble import ensemble_pipeline

# Read the netlist (use clean version without .control blocks)
netlist_path = Path(__file__).parent.parent / 'examples/netlists/test_netlist_simple.cir'
netlist = netlist_path.read_text()

print("=" * 72)
print(" TESTING HYBRID ENSEMBLE WITH NMOS DC SWEEP")
print("=" * 72)
print(f"\nNetlist: {netlist_path}")
print(f"Lines: {len(netlist.splitlines())}")
print("\nRunning ensemble pipeline...\n")

# Run hybrid ensemble
result = ensemble_pipeline(
    netlist,
    output_dir="/tmp/hybrid_nmos_test",
    cache=True,
    parallel=True,
)

# Display results
print("\n" + "=" * 72)
print(" FINAL RESULTS")
print("=" * 72)
print(f"\nWinner:           {result['winner']}")
print(f"Best model:       {result['va_path']}")
print(f"AI NRMSE:         {result['ai_nrmse']:.6f}")
print(f"Prog NRMSE:       {result['prog_nrmse']:.6f}")
print(f"Improvement:      {result['improvement']:.2f}%")
print(f"\nTelemetry:")
print(f"  Total time:     {result['telemetry']['total_time']:.2f}s")
print(f"  AI time:        {result['telemetry']['ai_time']:.2f}s")
print(f"  Prog time:      {result['telemetry']['prog_time']:.2f}s")
print(f"  Parallel:       {result['telemetry']['parallel']}")
print(f"  Cache hit:      {result['cache_hit']}")

if result['va_code']:
    print(f"\n" + "=" * 72)
    print(" GENERATED VERILOG-AMS")
    print("=" * 72)
    print(result['va_code'])

print("\n" + "=" * 72)
print(" TEST COMPLETE")
print("=" * 72)
