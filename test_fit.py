#!/usr/bin/env python3
"""
Test the fitting function with simple data
"""

import numpy as np
from fit_transfer_function_dc_sweep import fit_transfer_function

# Create test data similar to MOSFET
x = np.linspace(0, 1.8, 50)
y = np.where(x > 0.4, 4.2e-5 * (x - 0.4)**2, 0)

print("Testing fit_transfer_function...")
print(f"x shape: {x.shape}")
print(f"y shape: {y.shape}")
print(f"x range: [{x.min():.3f}, {x.max():.3f}]")
print(f"y range: [{y.min():.3e}, {y.max():.3e}]")

try:
    result = fit_transfer_function(x, y)
    print("\nSuccess!")
    print(f"Intent: {result['intent']}")
    print(f"Model type: {result['model_type']}")
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
