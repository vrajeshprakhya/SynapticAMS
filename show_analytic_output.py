#!/usr/bin/env python3
"""
Show what a complete analytic model output looks like
"""

import numpy as np
from fit_transfer_function_dc_sweep import fit_transfer_function
from pprint import pprint

# Create clean quadratic data (should produce analytic model)
x = np.linspace(0, 1.5, 50)
y = np.where(x > 0.4, 4.2e-5 * (x - 0.4)**2, 0)

print("Testing fit with clean saturating data...")
print(f"x: {x.shape} points from {x.min():.2f} to {x.max():.2f}")
print(f"y: {y.shape} points from {y.min():.2e} to {y.max():.2e}")

model = fit_transfer_function(x, y)

print("\n" + "="*60)
print("COMPLETE MODEL STRUCTURE")
print("="*60)
pprint(model, width=100, depth=6)

if model['model_type'] == 'analytic':
    print("\n" + "="*60)
    print("TRANSFER FUNCTION DETAILS")
    print("="*60)

    print(f"\nIntent: {model['intent']}")
    print(f"Fit quality (NRMSE): {model['nrmse']:.8f}")

    inner_model = model['model']

    print(f"\n📊 REGIONS:")
    for i, region in enumerate(inner_model['regions']):
        print(f"\n  Region {i+1}: {region['name']}")
        print(f"    Expression: {region['expr']}")
        print(f"    Range: {region['range']}")
        if 'params' in region:
            print(f"    Parameters:")
            for k, v in region['params'].items():
                print(f"      {k} = {v:.6e}")

    print(f"\n🔧 SMOOTHING:")
    smooth = inner_model['smoothing']
    print(f"  Method: {smooth['type']}")
    print(f"  Transition center: {smooth['center']:.6f} V")
    print(f"  Transition width: {smooth['width']:.6f} V")

    print(f"\n📐 GLOBAL PARAMETERS:")
    for k, v in inner_model['params'].items():
        print(f"  {k} = {v:.6e}")

    print("\n" + "="*60)
    print("VERILOG-AMS PSEUDOCODE")
    print("="*60)

    Vth = smooth['center']
    delta = smooth['width']
    k = inner_model['params']['k']

    verilog_code = f"""
module transfer_function(output electrical vout, input electrical vin);
    analog begin
        real w, vout_val;

        // Smooth weight function
        w = 0.5 * (1.0 + tanh((V(vin) - {Vth:.6f}) / {delta:.6f}));

        // Blended transfer function
        // Off region: vout = 0
        // On region:  vout = {k:.6e} * (vin - {Vth:.6f})^2
        vout_val = w * {k:.6e} * pow(max(V(vin) - {Vth:.6f}, 0.0), 2);

        V(vout) <+ vout_val;
    end
endmodule
"""

    print(verilog_code)

else:
    print(f"\n❌ Model type: {model['model_type']}")
    print(f"   Reason: {model.get('reason', 'N/A')}")
