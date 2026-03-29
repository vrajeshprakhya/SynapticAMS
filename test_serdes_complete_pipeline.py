#!/usr/bin/env python3
"""
Run SerDes netlist through complete pipeline with remote Ollama.

This test demonstrates the full SynapticAMS pipeline with:
- Automatic transient extraction fallback
- Remote Ollama instance at http://192.168.1.168:11434/
- Complete SerDes circuit analysis
"""

import sys
import time
from pathlib import Path

# Add pipeline_ext to path
sys.path.insert(0, str(Path(__file__).parent))

from pipeline_ext.complete_pipeline import spice_to_verilog_ams


def main():
    print("="*80)
    print(" SERDES COMPLETE PIPELINE TEST")
    print("="*80)
    print()
    print("Configuration:")
    print("  Netlist:  serdes_top.cir")
    print("  AI:       Ollama @ http://192.168.1.168:11434/")
    print("  Features: Transient extraction fallback enabled")
    print("  Output:   ./output_serdes_complete/")
    print()

    # Read SerDes netlist
    netlist_path = Path("serdes_top.cir")
    if not netlist_path.exists():
        print(f"Error: {netlist_path} not found")
        return 1

    print(f"Reading {netlist_path}...")
    netlist = netlist_path.read_text()
    print(f"  {len(netlist)} characters")
    print(f"  {len(netlist.splitlines())} lines")
    print()

    # Run complete pipeline
    print("Starting pipeline...")
    print()

    start_time = time.time()

    try:
        saved_files = spice_to_verilog_ams(
            netlist,
            output_dir='./output_serdes_complete'
        )

        elapsed = time.time() - start_time

        print()
        print("="*80)
        print(" PIPELINE COMPLETE!")
        print("="*80)
        print(f"\nTime elapsed: {elapsed:.1f} seconds")
        print(f"Files generated: {len(saved_files)}")
        print()
        print("Generated files:")
        for f in saved_files:
            print(f"  - {f.name}")

        # Show summary of .va files
        va_files = [f for f in saved_files if str(f).endswith('.va')]
        print(f"\nVerilog-AMS modules: {len(va_files)}")
        for va_file in va_files:
            print(f"\n{'='*80}")
            print(f" {va_file.name}")
            print("="*80)
            # Show first 30 lines
            with open(va_file, 'r') as f:
                lines = f.readlines()
                for i, line in enumerate(lines[:30], 1):
                    print(f"{i:3d}: {line.rstrip()}")
                if len(lines) > 30:
                    print(f"     ... ({len(lines) - 30} more lines)")

        return 0

    except Exception as e:
        print()
        print("="*80)
        print(" PIPELINE FAILED")
        print("="*80)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
