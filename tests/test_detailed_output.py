#!/usr/bin/env python3
"""
Test pipeline and show detailed transfer function output
"""

from pipeline_example import run_pipeline
from pprint import pprint

test_netlist = """
* Common source amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

print("Running pipeline...\n")
models = run_pipeline(test_netlist)

print("\n" + "="*60)
print("DETAILED TRANSFER FUNCTION OUTPUT")
print("="*60)

for i, fitted_model in enumerate(models):
    print(f"\n{'='*60}")
    print(f"MODEL {i+1}: {fitted_model['output']} = f({fitted_model['input']})")
    print("="*60)

    print("\nComplete model structure:")
    pprint(fitted_model['model'], width=100, depth=5)

    print(f"\nData shape:")
    print(f"  x: {fitted_model['data']['x'].shape} points")
    print(f"  y: {fitted_model['data']['y'].shape} points")

    model = fitted_model['model']

    if model['model_type'] == 'analytic':
        print("\n✓ ANALYTIC MODEL")
        print(f"  Intent: {model['intent']}")
        print(f"  NRMSE: {model['nrmse']:.6f}")

        if 'model' in model:
            inner_model = model['model']
            print(f"\n  Model type: {inner_model.get('model', 'unknown')}")

            if 'regions' in inner_model:
                print(f"\n  Regions ({len(inner_model['regions'])}):")
                for region in inner_model['regions']:
                    print(f"    - {region.get('name', 'unnamed')}: {region.get('expr', 'no expr')}")
                    print(f"      Range: {region.get('range', 'N/A')}")
                    if 'params' in region:
                        print(f"      Params: {region['params']}")

            if 'smoothing' in inner_model:
                print(f"\n  Smoothing:")
                print(f"    Type: {inner_model['smoothing'].get('type')}")
                print(f"    Center: {inner_model['smoothing'].get('center')}")
                print(f"    Width: {inner_model['smoothing'].get('width')}")

            if 'params' in inner_model:
                print(f"\n  Global parameters:")
                for key, val in inner_model['params'].items():
                    print(f"    {key}: {val}")

    elif model['model_type'] == 'LUT':
        print("\n✗ LOOKUP TABLE (LUT)")
        print(f"  Intent: {model['intent']}")
        print(f"  Reason: {model.get('reason', 'not specified')}")
        print(f"\n  → Would need to store full (x, y) data table")
        print(f"     {len(fitted_model['data']['x'])} data points")
