#!/usr/bin/env python3
"""Test baseline model validation against fixed SPICE"""
import sys
sys.path.insert(0, '/home/vrajeshprakhya/SynapticAMS')

from demo_warmstart_validated import validate_module

# Read the baseline model
with open('/tmp/serdes_final_model/baseline/serdes_rx_system.va', 'r') as f:
    baseline_va = f.read()

# Read the SPICE netlist
with open('/tmp/flattened_serdes.cir', 'r') as f:
    spice_netlist = f.read()

# Block info
block_info = {
    'inputs': ['tx_p_src', 'tx_n_src'],
    'outputs': ['final_out']
}

# Run validation
from pathlib import Path
success, metrics, reason = validate_module(
    module_name='serdes_rx_system',
    verilog_ams_code=baseline_va,
    spice_netlist=spice_netlist,
    block_info=block_info,
    output_dir=Path('/tmp/serdes_final_model/baseline')
)

print(f"\n{'='*70}")
print(f"VALIDATION RESULT: {'PASS ✓' if success else 'FAIL ✗'}")
print(f"{'='*70}")
if metrics:
    for key, value in metrics.items():
        print(f"  {key}: {value}")
if reason:
    print(f"\nReason: {reason}")
print(f"{'='*70}\n")
