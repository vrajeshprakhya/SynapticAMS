#!/usr/bin/env python3
"""
Full SerDes Test — Hybrid Ensemble Pipeline
============================================
Tests the complete hybrid ensemble (AI + programmatic) on the SerDes
TX-to-RX data path circuit.

Circuit:  examples/netlists/serdes_cml.cir
  - TX Differential Driver (NMOS diff pair, CML topology, 1.8V)
  - RC Channel  (5 Ω + 200 fF per side — 5 cm PCB trace model)
  - RX Differential Amplifier (NMOS diff pair, 1600Ω load)
  - DC transfer: VOL=1.0V, VOH=1.8V, Gain≈5V/V, BW≈200MHz

Why NOT serdes_top.cir:
  serdes_top.cir includes a 7-stage ring VCO (blocks/vco_sub.cir) that
  uses XSPICE adc_bridge elements.  XSPICE hybrid elements block ngspice
  DC analysis entirely, making DC sweep — the foundation of this pipeline
  — impossible.  The .DC directive in serdes_top.cir is also commented
  out for this reason.  serdes_cml.cir is the DC-sweepable CML data path.

AI Backend: local Ollama (localhost:11434) — falls back to Claude if
  ANTHROPIC_API_KEY is set.
"""

from pathlib import Path
from hybrid_ensemble import ensemble_pipeline
import sys
import time


NETLIST_PATH = Path('examples/netlists/serdes_cml.cir')


def main():
    if not NETLIST_PATH.exists():
        print(f"❌ Netlist not found: {NETLIST_PATH}", file=sys.stderr)
        return 1

    netlist = NETLIST_PATH.read_text()

    print("=" * 80)
    print("FULL SERDES TEST — HYBRID ENSEMBLE PIPELINE")
    print("=" * 80)
    print(f"Netlist:     {NETLIST_PATH}")
    print(f"Components:  TX CML Driver (NMOS 1.8V) → PCB Channel → RX Amplifier")
    print(f"AI Backend:  local Ollama (auto-detects Claude if API key set)")
    print(f"Mode:        Parallel execution (AI + Programmatic)")
    print(f"Cache:       Disabled (fresh test)")
    print("=" * 80)
    print()

    start_time = time.time()

    try:
        result = ensemble_pipeline(
            netlist,
            output_dir='./output_serdes_full',
            cache=False,
        )

        elapsed = time.time() - start_time

        print()
        print("=" * 80)
        print("FULL SERDES HYBRID ENSEMBLE RESULTS")
        print("=" * 80)
        print()
        print("WINNER:")
        print(f"  {result['winner'].upper()}")
        print()
        print("PERFORMANCE COMPARISON:")
        ai_nrmse = result['ai_nrmse']
        prog_nrmse = result['prog_nrmse']
        if ai_nrmse != float('inf'):
            print(f"  AI Pipeline:           ✓  NRMSE = {ai_nrmse:.4f}")
        else:
            print(f"  AI Pipeline:           ✗  Failed or no data")
        if prog_nrmse != float('inf'):
            print(f"  Programmatic Pipeline: ✓  NRMSE = {prog_nrmse:.4f}")
        else:
            print(f"  Programmatic Pipeline: ✗  Failed or no data")

        print()
        print("TIMING:")
        t = result['telemetry']
        print(f"  Total time:  {t['total_time']:.2f}s")
        print(f"  AI time:     {t['ai_time']:.2f}s")
        print(f"  Prog time:   {t['prog_time']:.2f}s")
        if 'speedup' in t:
            print(f"  Speedup:     {t['speedup']:.2f}x (parallel)")
        print()
        print("OUTPUT:")
        print(f"  Best model:  {result['va_path']}")
        print()
        if result.get('va_code'):
            print("=" * 80)
            print("GENERATED VERILOG-AMS")
            print("=" * 80)
            print(result['va_code'])
        print("=" * 80)

        return 0

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ ERROR after {elapsed:.1f}s: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
