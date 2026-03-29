#!/usr/bin/env python3
"""
Test the OpenSERDES complete SerDes through the hybrid ensemble pipeline
"""

import os
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from hybrid_ensemble import ensemble_pipeline
import time

def main():
    print("=" * 80)
    print(" OPENSERDES HYBRID ENSEMBLE PIPELINE")
    print("=" * 80)
    print()
    print("Configuration:")
    print("  Test:      OpenSERDES Complete SerDes (TX -> Channel -> RX)")
    print("  AI:        Ollama @ http://192.168.1.168:11434/")
    print("  Pipeline:  AI + Programmatic (parallel)")
    print("  Output:    ./output_openserdes_hybrid/")
    print()

    # Read the OpenSERDES netlist
    netlist_path = "openserdes_complete.cir"
    with open(netlist_path) as f:
        netlist = f.read()

    print(f"Reading {netlist_path}...")
    print(f"  {len(netlist)} characters, {netlist.count(chr(10))} lines")
    print()

    print("Starting HYBRID ENSEMBLE pipeline...")
    print("This will run AI and Programmatic pipelines in parallel!")
    print()

    start_time = time.time()

    # Run the hybrid ensemble
    result = ensemble_pipeline(
        netlist,
        output_dir='./output_openserdes_hybrid',
        cache=False,
        parallel=True,
        ai_kwargs={'provider': 'ollama'}  # Use remote Ollama
    )

    elapsed = time.time() - start_time

    # Display results
    print()
    print("=" * 80)
    print(" HYBRID ENSEMBLE COMPLETE!")
    print("=" * 80)
    print()
    print(f"Time elapsed: {elapsed:.1f} seconds")
    print()
    print("Results:")
    print(f"  Winner:      {result.get('winner', 'unknown')}")
    ai_nrmse = result.get('ai_nrmse')
    prog_nrmse = result.get('programmatic_nrmse')
    print(f"  AI NRMSE:    {ai_nrmse:.4f}" if ai_nrmse is not None else "  AI NRMSE:    N/A")
    print(f"  Prog NRMSE:  {prog_nrmse:.4f}" if prog_nrmse is not None else "  Prog NRMSE:  N/A")
    print()
    print(f"  AI Time:     {result.get('ai_time', 0):.1f}s")
    print(f"  Prog Time:   {result.get('programmatic_time', 0):.1f}s")
    print()

    # Show winner details
    if result['winner'] == 'ai':
        print("AI Pipeline:")
        print(f"  File:        {result.get('ai_output_file', 'N/A')}")
        print(f"  NRMSE:       {result['ai_nrmse']:.4f}" if result['ai_nrmse'] is not None else "  NRMSE:       N/A")
    else:
        print("Programmatic Pipeline:")
        prog_files = result.get('programmatic_output_files', [])
        print(f"  Files:       {len(prog_files)} modules")
        for i, f in enumerate(prog_files[:5]):
            fname = os.path.basename(f)
            print(f"    - {fname}")
        if len(prog_files) > 5:
            print(f"    ... and {len(prog_files) - 5} more")

    print()
    print("=" * 80)
    print(f" WINNER: {result['winner'].upper()}")
    print("=" * 80)
    print()

    # Show best model snippet if available
    if result['winner'] == 'programmatic' and result.get('programmatic_output_files'):
        first_file = result['programmatic_output_files'][0]
        if os.path.exists(first_file):
            print(f"Best models: {len(result['programmatic_output_files'])} Verilog-AMS modules")
            print()
            print("Sample model (first file):")
            print()
            with open(first_file) as f:
                lines = f.readlines()
                print("First 30 lines:")
                for i, line in enumerate(lines[:30], 1):
                    print(f"{i:3d}: {line.rstrip()}")
                if len(lines) > 30:
                    print(f"     ... ({len(lines) - 30} more lines)")

if __name__ == '__main__':
    main()
