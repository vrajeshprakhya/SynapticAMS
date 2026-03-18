#!/usr/bin/env python3
"""
Test Hybrid Ensemble Pipeline with Remote Ollama
Tests the SerDes circuit with AI (remote Ollama) + Programmatic pipelines running in parallel
"""

from pathlib import Path
from hybrid_ensemble import ensemble_pipeline
import sys

def main():
    # Load SerDes netlist
    netlist_path = Path(__file__).parent.parent / 'examples/netlists/serdes_top.cir'
    with open(netlist_path, 'r') as f:
        netlist = f.read()

    print("="*80)
    print("TESTING HYBRID ENSEMBLE WITH REMOTE OLLAMA")
    print("="*80)
    print(f"Netlist:     examples/netlists/serdes_top.cir")
    print(f"AI Backend:  Ollama @ http://192.168.1.31:11434")
    print(f"AI Model:    llama3.2:3b (auto-selected)")
    print(f"Mode:        Parallel execution")
    print(f"Cache:       Disabled (fresh test)")
    print("="*80)
    print()

    try:
        result = ensemble_pipeline(
            netlist,
            output_dir='./output_hybrid_remote_ollama',
            cache=False,  # Disable cache for fresh test
            parallel=True,
            ai_kwargs={'provider': 'ollama'}  # Use Ollama backend
        )

        print()
        print("="*80)
        print("HYBRID ENSEMBLE RESULTS")
        print("="*80)
        print(f"Winner:          {result['winner'].upper()}")
        print(f"AI NRMSE:        {result['ai_nrmse']:.4f}")
        print(f"Prog NRMSE:      {result['prog_nrmse']:.4f}")
        print(f"Improvement:     {result['improvement']:.1f}%")
        print(f"Best model:      {result['va_path']}")
        print()
        print(f"Total time:      {result['telemetry']['total_time']:.2f}s")
        print(f"  AI time:       {result['telemetry']['ai_time']:.2f}s")
        print(f"  Prog time:     {result['telemetry']['prog_time']:.2f}s")
        if 'speedup' in result['telemetry']:
            print(f"Speedup:         {result['telemetry']['speedup']:.2f}x (parallel)")
        print("="*80)

        return 0

    except Exception as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
