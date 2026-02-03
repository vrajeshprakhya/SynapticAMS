#!/usr/bin/env python3
import numpy as np
from fit_transfer_function_dc_sweep import fit_transfer_function
from verilog_ams_generator import VerilogAMSGenerator

# Create test data
x = np.linspace(0, 1.5, 50)
y = np.where(x > 0.4, 4.2e-5 * (x - 0.4)**2, 0)

# Fit model
model = fit_transfer_function(x, y)

# Print the regions
print("Model regions:")
for region in model['model']['regions']:
    print(f"  {region['name']}: expr = '{region['expr']}'")

# Create fitted model structure
fitted_model = {
    'input': 'vin',
    'output': 'vout',
    'model': model,
    'data': {'x': x, 'y': y}
}

# Generate Verilog-AMS
generator = VerilogAMSGenerator()

# Add debug to _translate_expr
original_translate = generator._translate_expr

def debug_translate(expr, input_name, params):
    print(f"\n_translate_expr called:")
    print(f"  Input expr: '{expr}'")
    result = original_translate(expr, input_name, params)
    print(f"  Output: '{result}'")
    return result

generator._translate_expr = debug_translate

code = generator.generate_module(fitted_model, 'test')
print("\n" + "="*60)
print("Generated code (y_on line):")
for line in code.split('\n'):
    if 'y_on' in line:
        print(line)
