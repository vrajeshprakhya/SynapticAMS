#!/usr/bin/env python3
"""
Run SerDes through HYBRID ENSEMBLE pipeline with remote Ollama.

This runs BOTH:
1. AI Pipeline (Ollama-based Verilog-AMS generation)
2. Programmatic Pipeline (transfer function fitting)

Then compares them and returns the best model!
"""

import sys
import time
from pathlib import Path

# Add to path if needed
sys.path.insert(0, str(Path(__file__).parent))

from hybrid_ensemble import ensemble_pipeline


def main():
    print("="*80)
    print(" SERDES HYBRID ENSEMBLE PIPELINE")
    print("="*80)
    print()
    print("Configuration:")
    print("  Test:      SerDes (VCO + TX + RX)")
    print("  AI:        Ollama @ http://192.168.1.168:11434/")
    print("  Pipeline:  AI + Programmatic (parallel)")
    print("  Output:    ./output_serdes_hybrid/")
    print()

    # Read SerDes netlist
    netlist_path = Path("serdes_top.cir")
    if not netlist_path.exists():
        print(f"Error: {netlist_path} not found")
        return 1

    print(f"Reading {netlist_path}...")
    netlist = netlist_path.read_text()
    print(f"  {len(netlist)} characters, {len(netlist.splitlines())} lines")
    print()

    # Run hybrid ensemble pipeline
    print("Starting HYBRID ENSEMBLE pipeline...")
    print("This will run AI and Programmatic pipelines in parallel!")
    print()

    start_time = time.time()

    try:
        result = ensemble_pipeline(
            netlist,
            output_dir='./output_serdes_hybrid',
            cache=False,  # Disable cache for fresh test
            parallel=True,  # Run both pipelines in parallel
            ai_kwargs={'provider': 'ollama'}  # Use remote Ollama
        )

        elapsed = time.time() - start_time

        print()
        print("="*80)
        print(" HYBRID ENSEMBLE COMPLETE!")
        print("="*80)
        print(f"\nTime elapsed: {elapsed:.1f} seconds")
        print()

        # Show detailed results
        print("Results:")
        print(f"  Winner:      {result['winner']}")
        print(f"  AI NRMSE:    {result['ai_nrmse']:.4f}" if result.get('ai_nrmse') is not None else "  AI NRMSE:    N/A")
        print(f"  Prog NRMSE:  {result['prog_nrmse']:.4f}" if result.get('prog_nrmse') is not None else "  Prog NRMSE:  N/A")
        print()

        # Extract timing from nested results
        ai_time = result.get('ai_result', {}).get('time')
        prog_time = result.get('prog_result', {}).get('time')

        if ai_time is not None:
            print(f"  AI Time:     {ai_time:.1f}s")
        if prog_time is not None:
            print(f"  Prog Time:   {prog_time:.1f}s")
        print()

        # Show AI result details
        if result.get('ai_result'):
            ai = result['ai_result']
            print("AI Pipeline:")
            print(f"  File:        {ai.get('va_path', 'N/A')}")
            print(f"  NRMSE:       {ai.get('nrmse', 'N/A')}")
            print()

        # Show Programmatic result details
        if result.get('prog_result'):
            prog = result['prog_result']
            print("Programmatic Pipeline:")
            print(f"  Files:       {len(prog.get('va_files', []))} modules")
            if prog.get('va_files'):
                for f in prog['va_files'][:5]:  # Show first 5
                    print(f"    - {f.name}")
                if len(prog['va_files']) > 5:
                    print(f"    ... and {len(prog['va_files']) - 5} more")
            print()

        # Show winner file
        print("="*80)
        print(f" WINNER: {result['winner'].upper()}")
        print("="*80)

        if result['winner'] == 'ai' and result.get('ai_result', {}).get('va_path'):
            winner_path = result['ai_result']['va_path']
            print(f"\nBest model: {winner_path}")
            try:
                with open(winner_path, 'r') as f:
                    print("\nFirst 40 lines:")
                    lines = f.readlines()
                    for i, line in enumerate(lines[:40], 1):
                        print(f"{i:3d}: {line.rstrip()}")
                    if len(lines) > 40:
                        print(f"     ... ({len(lines) - 40} more lines)")
            except FileNotFoundError:
                print(f"  (File not found: {winner_path})")

        elif result['winner'] == 'programmatic' and result.get('prog_result', {}).get('va_files'):
            prog_files = result['prog_result']['va_files']
            print(f"\nBest models: {len(prog_files)} Verilog-AMS modules")
            print("\nSample model (first file):")
            try:
                with open(prog_files[0], 'r') as f:
                    print("\nFirst 30 lines:")
                    lines = f.readlines()
                    for i, line in enumerate(lines[:30], 1):
                        print(f"{i:3d}: {line.rstrip()}")
                    if len(lines) > 30:
                        print(f"     ... ({len(lines) - 30} more lines)")
            except (FileNotFoundError, IndexError):
                pass

        return 0

    except Exception as e:
        print()
        print("="*80)
        print(" HYBRID ENSEMBLE FAILED")
        print("="*80)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
