#!/usr/bin/env python3
"""
Quick test of Remote Ollama with simple VCO circuit
"""

from hybrid_ensemble import ensemble_pipeline

# Load simple VCO netlist
with open('test_vco_simple.cir', 'r') as f:
    netlist = f.read()

print("="*80)
print("QUICK TEST: Remote Ollama with VCO Circuit")
print("="*80)
print(f"Netlist:     test_vco_simple.cir (3-stage ring oscillator)")
print(f"AI Backend:  Ollama @ http://192.168.1.31:11434")
print(f"Mode:        Parallel execution")
print("="*80)
print()

result = ensemble_pipeline(
    netlist,
    output_dir='./output_vco_remote_ollama',
    cache=False,
    parallel=True,
    ai_kwargs={'provider': 'ollama'}
)

print()
print("="*80)
print("RESULTS")
print("="*80)
print(f"Winner:       {result['winner'].upper()}")
print(f"AI Status:    {'✓ Success' if result['ai_nrmse'] != float('inf') else '✗ Failed'}")
print(f"Prog Status:  {'✓ Success' if result['prog_nrmse'] != float('inf') else '✗ Failed'}")
print(f"Total time:   {result['telemetry']['total_time']:.2f}s")
print("="*80)
