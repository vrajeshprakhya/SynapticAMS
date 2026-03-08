#!/usr/bin/env python3
"""
Process OpenSERDES Receiver through the pipeline
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))



from complete_pipeline import spice_to_verilog_ams
from pathlib import Path

# Read the receiver netlist
netlist_path = Path('/home/vrajeshprakhya/eda_tools/OpenSERDES/Receiver_Bypassing_CDR/test_receiver.cir')

with open(netlist_path, 'r') as f:
    netlist_text = f.read()

print("="*70)
print(" OpenSERDES RECEIVER → VERILOG-AMS CONVERSION")
print("="*70)
print(f"\nInput netlist: {netlist_path}")
print(f"Size: {len(netlist_text)} characters\n")

# Run the pipeline
output_dir = Path('/home/vrajeshprakhya/circuit_preprocess')
saved_files = spice_to_verilog_ams(netlist_text, str(output_dir))

# Display generated Verilog-AMS files
print("\n" + "="*70)
print(" GENERATED VERILOG-AMS FILES")
print("="*70)

va_files = [f for f in saved_files if str(f).endswith('.va')]

for f in va_files:
    print(f"\n{'='*70}")
    print(f" File: {f.name}")
    print("="*70)
    with open(f, 'r') as file:
        content = file.read()
        print(content)

print(f"\n\nTotal Verilog-AMS modules generated: {len(va_files)}")
