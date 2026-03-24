#!/usr/bin/env python3
"""
test_pll_demo.py — VCO characterization + Verilog-AMS generation demo

Demonstrates the SynapticAMS pipeline applied to the clock-generation
block of a SerDes:

  SPICE netlist (vco_ring5.cir)
      │
      ▼  ngspice .TRAN × N bias points
  (Vctrl, f_osc) pairs
      │
      ▼  linear Kvco fit
  Kvco = 334 MHz/V,  f_ref = 87 MHz @ 0.90 V
      │
      ▼  generate_vco_va()
  Verilog-AMS module VCO_RING5

The generated model is the analog front-end piece of a PLL CDR:
  in a full SerDes, Vctrl is driven by the PLL loop filter and the
  VCO locks to N × f_data_rate / 2 (Nyquist).

Run:
    python tests/test_pll_demo.py
"""

import sys
import time
from pathlib import Path

# Ensure project root is on sys.path when run from anywhere
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline import vco_tran_sweep, run_vco_pipeline


NETLIST_PATH = Path(__file__).parent.parent / 'examples/netlists/vco_ring5.cir'
OUTPUT_DIR   = Path(__file__).parent.parent / 'output_pll_demo'


def print_banner(title):
    print("=" * 68)
    print(f" {title}")
    print("=" * 68)


def main():
    print_banner("SynapticAMS — VCO / PLL CHARACTERIZATION DEMO")
    print()
    print("Circuit:  5-stage current-starved ring VCO (Level-1 MOSFET, 1.8V)")
    print("Netlist: ", NETLIST_PATH.relative_to(Path(__file__).parent.parent))
    print()
    print("SerDes context:")
    print("  This VCO is the clock-generation core of the PLL CDR block.")
    print("  The full SerDes chain modeled by SynapticAMS:")
    print("    TX CML driver  → (serdes_cml.cir, DC pipeline,  laplace_nd model)")
    print("    PCB channel    → (serdes_cml.cir, DC pipeline,  RC passthrough)")
    print("    RX CML amp     → (serdes_cml.cir, DC pipeline,  laplace_nd model)")
    print("    VCO / PLL CDR  → (vco_ring5.cir,  TRAN pipeline, idtmod model)  ← this demo")
    print()

    if not NETLIST_PATH.exists():
        print(f"ERROR: netlist not found: {NETLIST_PATH}", file=sys.stderr)
        sys.exit(1)

    netlist = NETLIST_PATH.read_text()

    # ── Step 1: Full pipeline (sweep + fit + generate + save) ──────────
    print_banner("Running run_vco_pipeline()")
    t0 = time.time()

    va_path, vco_metrics = run_vco_pipeline(
        netlist,
        output_dir=str(OUTPUT_DIR),
        ctrl_source='Vctrl',
        output_node='vout',
        vctrl_range=(0.70, 1.20),
        n_points=7,
    )

    elapsed = time.time() - t0

    # ── Step 2: Print results ──────────────────────────────────────────
    print()
    print_banner("RESULTS")
    print()
    print(f"  Runtime:      {elapsed:.1f} s")
    print(f"  Kvco:         {vco_metrics['kvco'] / 1e6:.1f} MHz/V")
    print(f"  f_ref:        {vco_metrics['f_ref'] / 1e6:.1f} MHz  "
          f"@ Vctrl = {vco_metrics['vctrl_ref']:.2f} V")
    print(f"  Linearity R²: {vco_metrics['r_squared']:.4f}")
    print()
    print(f"  Frequency table:")
    for vc, f in zip(vco_metrics['vctrl'], vco_metrics['frequencies']):
        bar = '█' * int(f / 1e6 / 10)
        print(f"    Vctrl={vc:.2f}V  {f/1e6:6.1f} MHz  {bar}")
    print()
    print(f"  Output: {va_path}")
    print()

    # ── Step 3: Show generated Verilog-AMS ────────────────────────────
    print_banner("GENERATED VERILOG-AMS")
    print()
    print(va_path.read_text())

    # ── Step 4: Validate structure ────────────────────────────────────
    va_code = va_path.read_text()
    checks = [
        ('`include "disciplines.vams"', "disciplines.vams included"),
        ('`include "constants.vams"',   "constants.vams included"),
        ('idtmod(',                     "idtmod used for phase integration"),
        ('`M_PI',                       "M_PI constant used"),
        ('Kvco',                        "Kvco parameter present"),
        ('f_ref',                       "f_ref parameter present"),
        ('V(out) <+',                   "contribution statement present"),
    ]
    print_banner("VALIDATION")
    all_pass = True
    for pattern, label in checks:
        ok = pattern in va_code
        all_pass = all_pass and ok
        print(f"  {'✓' if ok else '✗'}  {label}")

    print()
    if all_pass:
        print("  All checks passed — Verilog-AMS structure is correct.")
    else:
        print("  Some checks failed — review generated model.", file=sys.stderr)

    print()
    print_banner("DONE")
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
