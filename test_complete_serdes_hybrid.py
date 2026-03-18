#!/usr/bin/env python3
"""
Test the Complete SerDes (VCO + Serializer + TX + Channel + RX + Deserializer)
through the hybrid ensemble pipeline
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from hybrid_ensemble import ensemble_pipeline

def main():
    print("="*80)
    print(" COMPLETE SERDES HYBRID ENSEMBLE PIPELINE")
    print("="*80)
    print()
    print("Architecture:")
    print("  TX Side:   VCO → Serializer → TX Driver")
    print("  Channel:   RC transmission line")
    print("  RX Side:   RX Amplifier → DFF Sampler → Deserializer")
    print()
    print("Configuration:")
    print("  AI:        Ollama @ http://192.168.1.168:11434/")
    print("  Pipeline:  AI + Programmatic (parallel)")
    print("  Output:    ./output_complete_serdes/")
    print()

    # Read the complete SerDes netlist
    netlist_path = "complete_serdes.cir"
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
        output_dir='./output_complete_serdes',
        cache=False,
        parallel=True,
        ai_kwargs={'provider': 'ollama'}  # Use remote Ollama
    )

    elapsed = time.time() - start_time

    # Display results
    print()
    print("="*80)
    print(" HYBRID ENSEMBLE COMPLETE!")
    print("="*80)
    print()
    print(f"Time elapsed: {elapsed:.1f} seconds")
    print()
    print("Results:")
    print(f"  Winner:      {result.get('winner', 'unknown')}")

    ai_nrmse = result.get('ai_nrmse')
    prog_nrmse = result.get('prog_nrmse') or result.get('programmatic_nrmse')

    print(f"  AI NRMSE:    {ai_nrmse:.4f}" if ai_nrmse is not None and ai_nrmse != float('inf') else "  AI NRMSE:    N/A")
    print(f"  Prog NRMSE:  {prog_nrmse:.4f}" if prog_nrmse is not None and prog_nrmse != float('inf') else "  Prog NRMSE:  N/A")
    print()

    ai_time = result.get('ai_result', {}).get('time') or result.get('ai_time', 0)
    prog_time = result.get('prog_result', {}).get('time') or result.get('programmatic_time', 0)

    print(f"  AI Time:     {ai_time:.1f}s")
    print(f"  Prog Time:   {prog_time:.1f}s")
    print()

    # Show winner details
    if result.get('winner') == 'ai':
        print("AI Pipeline:")
        ai_file = result.get('ai_result', {}).get('output_file') or result.get('ai_output_file')
        print(f"  File:        {ai_file}")
    else:
        print("Programmatic Pipeline:")
        prog_files = result.get('prog_result', {}).get('output_files', []) or result.get('programmatic_output_files', [])
        print(f"  Files:       {len(prog_files)} modules")
        for i, f in enumerate(prog_files[:5]):
            fname = f if isinstance(f, str) else str(f)
            if '/' in fname:
                fname = fname.split('/')[-1]
            print(f"    - {fname}")
        if len(prog_files) > 5:
            print(f"    ... and {len(prog_files) - 5} more")

    print()
    print("="*80)
    print(f" WINNER: {result.get('winner', 'unknown').upper()}")
    print("="*80)

if __name__ == '__main__':
    main()
