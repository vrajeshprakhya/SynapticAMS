#!/usr/bin/env python3
"""
Test with a circuit that should produce analytic model
"""

from pipeline_example import run_pipeline
from pprint import pprint

# Simpler circuit: just NMOS with voltage source (should be saturating/quadratic)
test_netlist = """
* Simple NMOS saturation
M1 vd vg 0 0 NMOS W=10u L=1u
VDD vd 0 DC 1.8V
Vin vg 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

print("Testing with simple NMOS (should produce analytic quadratic model)")
print("="*60)

models = run_pipeline(test_netlist)

if models:
    print("\n" + "="*60)
    print("DETAILED TRANSFER FUNCTION OUTPUT")
    print("="*60)

    for fitted_model in models:
        print(f"\n{fitted_model['output']} = f({fitted_model['input']})")
        print("\nComplete model structure:")
        print("-"*60)
        pprint(fitted_model['model'], width=100, depth=6)

        model = fitted_model['model']

        if model['model_type'] == 'analytic':
            print("\n" + "="*60)
            print("ANALYTIC TRANSFER FUNCTION")
            print("="*60)

            if 'model' in model and 'regions' in model['model']:
                for region in model['model']['regions']:
                    print(f"\nRegion: {region.get('name', 'unnamed')}")
                    print(f"  Expression: {region.get('expr', 'N/A')}")
                    print(f"  Range: {region.get('range', 'N/A')}")
                    if 'params' in region:
                        print(f"  Parameters:")
                        for k, v in region['params'].items():
                            print(f"    {k} = {v}")

                if 'smoothing' in model['model']:
                    print(f"\nSmoothing:")
                    smooth = model['model']['smoothing']
                    print(f"  Type: {smooth.get('type')}")
                    print(f"  Center: {smooth.get('center'):.4f}")
                    print(f"  Width: {smooth.get('width'):.6f}")

                    print(f"\n  Verilog-A implementation:")
                    Vth = smooth.get('center')
                    delta = smooth.get('width')
                    k = model['model']['params'].get('k', 0)
                    print(f"    w = 0.5 * (1 + tanh((vin - {Vth:.4f}) / {delta:.6f}));")
                    print(f"    vout = w * {k:.6e} * pow(max(vin - {Vth:.4f}, 0), 2);")
else:
    print("\nNo models fitted")
