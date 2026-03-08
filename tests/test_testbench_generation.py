#!/usr/bin/env python3
"""
Test testbench generation and saving functionality
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from equivalence_checker import EquivalenceChecker
import tempfile
import shutil
import json

# Sample block for testing
test_spice_netlist = """
* Differential amplifier subcircuit
.subckt diff_amp inp inn vout vdd vss
  M1 vout inp nb vss NMOS W=20u L=1u
  M2 nb inn nb vss NMOS W=20u L=1u
  M3 nb nb vdd vdd PMOS W=40u L=1u
  Ibias nb vss DC 100uA
.ends

* Power supplies
VDD vdd 0 DC 1.8
VSS vss 0 DC 0

* Instantiate
Xdut inp inn vout vdd vss diff_amp

* Models
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
.model PMOS PMOS (LEVEL=1 VTO=-0.4 KP=50u)
"""

test_verilog_ams = """
`include "disciplines.vams"

module diff_amp(inp, inn, vout);
  input inp, inn;
  output vout;
  electrical inp, inn, vout;

  parameter real gain = 10.0;
  parameter real vdd = 1.8;

  analog begin
    V(vout) <+ gain * (V(inp) - V(inn));
    // Clamp to rails
    if (V(vout) > vdd) V(vout) <+ vdd;
    if (V(vout) < 0) V(vout) <+ 0;
  end
endmodule
"""

block_info = {
    'name': 'diff_amp',
    'simulation_axes': ['inp', 'inn'],
    'outputs': ['vout'],
    'behavior_class': 'differential'
}


def test_testbench_saving():
    """Test that testbenches are saved correctly"""

    # Create temporary output directory
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / 'testbenches'

        print("=" * 70)
        print("Testing Testbench Generation and Saving")
        print("=" * 70)
        print(f"Output directory: {output_dir}\n")

        # Create equivalence checker with testbench saving enabled
        checker = EquivalenceChecker(
            abs_tol=1e-3,
            rel_tol=0.05,
            testbench_output_dir=str(output_dir)
        )

        # Run equivalence check (this should generate testbenches)
        print("Running equivalence check...")
        try:
            result = checker.check_block_equivalence(
                spice_netlist=test_spice_netlist,
                verilog_ams_code=test_verilog_ams,
                block_info=block_info,
                test_strategy='grid'
            )
            print(f"Equivalence check completed: {result.passed}\n")
        except Exception as e:
            print(f"Note: Equivalence check may fail due to missing tools: {e}")
            print("Continuing to verify testbench files were generated...\n")

        # Verify directory structure
        block_dir = output_dir / 'diff_amp'
        spice_dir = block_dir / 'spice'
        vams_dir = block_dir / 'verilog_ams'
        manifest_file = block_dir / 'test_manifest.json'

        print("Checking directory structure:")
        print(f"  Block directory exists: {block_dir.exists()}")
        print(f"  SPICE directory exists: {spice_dir.exists()}")
        print(f"  Verilog-AMS directory exists: {vams_dir.exists()}")
        print(f"  Manifest file exists: {manifest_file.exists()}\n")

        if not block_dir.exists():
            print("✗ FAIL: Testbench directory not created")
            return False

        # Check SPICE testbenches
        spice_testbenches = list(spice_dir.glob('*.cir')) if spice_dir.exists() else []
        print(f"SPICE testbenches generated: {len(spice_testbenches)}")
        if spice_testbenches:
            for tb in sorted(spice_testbenches)[:3]:  # Show first 3
                print(f"  - {tb.name}")

        # Check Verilog-AMS testbenches
        vams_testbenches = list(vams_dir.glob('*.cir')) if vams_dir.exists() else []
        print(f"Verilog-AMS testbenches generated: {len(vams_testbenches)}")
        if vams_testbenches:
            for tb in sorted(vams_testbenches)[:3]:  # Show first 3
                print(f"  - {tb.name}")

        # Check manifest
        if manifest_file.exists():
            with open(manifest_file, 'r') as f:
                manifest = json.load(f)
            print(f"\nManifest contents:")
            print(f"  Block name: {manifest.get('block_name')}")
            print(f"  Total test vectors: {manifest.get('total_test_vectors')}")
            print(f"  Saved testbenches: {manifest.get('saved_testbenches')}")
            print(f"  Inputs: {manifest.get('inputs')}")
            print(f"  Outputs: {manifest.get('outputs')}")

        # Show sample testbench content
        if spice_testbenches:
            print(f"\n" + "=" * 70)
            print(f"Sample SPICE Testbench: {spice_testbenches[0].name}")
            print("=" * 70)
            content = spice_testbenches[0].read_text()
            print(content)

        if vams_testbenches:
            print(f"\n" + "=" * 70)
            print(f"Sample Verilog-AMS Testbench: {vams_testbenches[0].name}")
            print("=" * 70)
            content = vams_testbenches[0].read_text()
            print(content)

        # Verify testbenches were created
        success = len(spice_testbenches) > 0

        print("\n" + "=" * 70)
        if success:
            print("✓ PASS: Testbenches generated successfully")
        else:
            print("✗ FAIL: No testbenches generated")
        print("=" * 70)

        return success


if __name__ == "__main__":
    success = test_testbench_saving()
    sys.exit(0 if success else 1)
