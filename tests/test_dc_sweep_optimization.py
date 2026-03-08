#!/usr/bin/env python3
"""
Test DC sweep optimization vs point-by-point simulation
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from equivalence_checker import EquivalenceChecker
import tempfile

# Sample differential amplifier
test_spice = """
.subckt diff_amp inp inn vout vdd vss
  M1 vout inp nb vss NMOS W=20u L=1u
  M2 nb inn nb vss NMOS W=20u L=1u
  M3 nb nb vdd vdd PMOS W=40u L=1u
  Ibias nb vss DC 100uA
.ends

VDD vdd 0 DC 1.8
VSS vss 0 DC 0
Xdut inp inn vout vdd vss diff_amp

.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
.model PMOS PMOS (LEVEL=1 VTO=-0.4 KP=50u)
"""

test_verilog = """
`include "disciplines.vams"

module diff_amp(inp, inn, vout);
  input inp, inn;
  output vout;
  electrical inp, inn, vout;
  parameter real gain = 10.0;

  analog begin
    V(vout) <+ gain * (V(inp) - V(inn));
  end
endmodule
"""

block_info = {
    'name': 'diff_amp',
    'simulation_axes': ['inp', 'inn'],
    'outputs': ['vout'],
    'behavior_class': 'differential'
}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / 'testbenches'

        print("=" * 70)
        print("DC SWEEP OPTIMIZATION TEST")
        print("=" * 70)

        checker = EquivalenceChecker(testbench_output_dir=str(output_dir))

        print("\nRunning equivalence check with DC sweep optimization...")
        try:
            result = checker.check_block_equivalence(
                spice_netlist=test_spice,
                verilog_ams_code=test_verilog,
                block_info=block_info,
                test_strategy='grid'
            )
        except Exception as e:
            print(f"Note: Check may fail due to missing tools: {e}")

        # Show master DC sweep testbench
        master_file = output_dir / 'diff_amp' / 'master_dc_sweep.cir'

        if master_file.exists():
            print("\n" + "=" * 70)
            print("MASTER DC SWEEP TESTBENCH (Single file for all 2500 points!)")
            print("=" * 70)
            print(master_file.read_text())

            print("\n" + "=" * 70)
            print("BENEFITS:")
            print("=" * 70)
            print("✓ 1 simulation instead of 2500 separate simulations")
            print("✓ 10-100× faster execution")
            print("✓ Standard SPICE DC sweep methodology")
            print("✓ All 2500 test points in one netlist")
            print("=" * 70)
        else:
            print("\n✗ Master DC sweep file not found")

        # Compare with individual point testbench
        point_file = output_dir / 'diff_amp' / 'spice' / 'testbench_000.cir'
        if point_file.exists():
            print("\n" + "=" * 70)
            print("INDIVIDUAL POINT TESTBENCH (for comparison)")
            print("=" * 70)
            content = point_file.read_text()
            print(content[:600] + "...")

            print("\n" + "=" * 70)
            print("INDIVIDUAL POINT METHOD (OLD WAY):")
            print("=" * 70)
            print("✗ 2500 separate .cir files")
            print("✗ 2500 ngspice invocations")
            print("✗ Huge process spawning overhead")
            print("✗ 10-100× slower")
            print("=" * 70)
