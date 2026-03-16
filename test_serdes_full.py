#!/usr/bin/env python3
"""
Full SerDes Test with Remote Ollama
Complete test of the hybrid ensemble pipeline with the full SerDes circuit
"""

from hybrid_ensemble import ensemble_pipeline
import sys
import time

def main():
    # Load full SerDes netlist
    with open('serdes_top.cir', 'r') as f:
        netlist = f.read()

    print("="*80)
    print("FULL SERDES TEST WITH HYBRID ENSEMBLE + REMOTE OLLAMA")
    print("="*80)
    print(f"Netlist:     serdes_top.cir")
    print(f"Components:  VCO + TX Differential Driver + RX Differential Amplifier")
    print(f"AI Backend:  Ollama @ http://192.168.1.31:11434")
    print(f"AI Model:    qwen2.5-coder:7b (auto-selected)")
    print(f"Mode:        Parallel execution")
    print(f"Cache:       Disabled (fresh test)")
    print("="*80)
    print()

    start_time = time.time()

    try:
        result = ensemble_pipeline(
            netlist,
            output_dir='./output_serdes_full',
            cache=False,  # Disable cache for fresh test
            parallel=True,
            ai_kwargs={'provider': 'ollama'}  # Use Ollama backend
        )

        elapsed = time.time() - start_time

        print()
        print("="*80)
        print("FULL SERDES HYBRID ENSEMBLE RESULTS")
        print("="*80)
        print()
        print("WINNER:")
        print(f"  {result['winner'].upper()}")
        print()
        print("PERFORMANCE COMPARISON:")
        print(f"  AI Pipeline:")
        if result['ai_nrmse'] != float('inf'):
            print(f"    ✓ Success - NRMSE: {result['ai_nrmse']:.4f}")
        else:
            print(f"    ✗ Failed or no data")

        if result['prog_nrmse'] != float('inf'):
            print(f"  Programmatic Pipeline:")
            print(f"    ✓ Success - NRMSE: {result['prog_nrmse']:.4f}")
        else:
            print(f"  Programmatic Pipeline:")
            print(f"    ✗ Failed or no data")

        print()
        print("TIMING:")
        print(f"  Total time:      {result['telemetry']['total_time']:.2f}s")
        print(f"  AI time:         {result['telemetry']['ai_time']:.2f}s")
        print(f"  Prog time:       {result['telemetry']['prog_time']:.2f}s")
        if 'speedup' in result['telemetry']:
            print(f"  Speedup:         {result['telemetry']['speedup']:.2f}x (parallel)")
        print()
        print("OUTPUT:")
        print(f"  Best model:      {result['va_path']}")
        print()
        print("="*80)

        return 0

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ ERROR after {elapsed:.1f}s: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
