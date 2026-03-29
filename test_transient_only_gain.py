#!/usr/bin/env python3
"""
Test dynamic fitting with NO DC sweep (transient-only DC gain extraction).
This simulates the ring oscillator case where DC operating point doesn't exist.
"""
import numpy as np
from pipeline_ext.fit_transfer_function import fit_dynamic_transfer_function

print("=" * 80)
print("TEST: DC Gain Extraction from Transient Only (Ring Oscillator Case)")
print("=" * 80)
print()

# Simulate a circuit where DC sweep FAILED (returns None/empty)
dc_x = None  # No DC sweep data (like ring oscillators)
dc_y = None

# Simulate transient step response data
# First-order system: V(t) = Vfinal * (1 - exp(-t/tau)) + Vinitial
# With DC gain = 5, tau = 1ns, step input = 1V

time = np.linspace(0, 10e-9, 100)  # 10ns, 100 points
tau = 1e-9  # 1ns time constant
dc_gain_true = 5.0  # True DC gain
initial_value = 0.1
final_value = initial_value + dc_gain_true * 1.0  # Step of 1V

# Generate step response
transient_voltage = initial_value + (final_value - initial_value) * (1 - np.exp(-time/tau))

print("Input Data:")
print(f"  DC Sweep: {dc_x} (FAILED - simulating ring oscillator)")
print(f"  Transient: {len(time)} points over {time[-1]*1e9:.1f}ns")
print(f"  Expected DC gain: {dc_gain_true}")
print(f"  Expected time constant: {tau*1e9:.1f}ns")
print()

# Fit dynamic transfer function (should extract DC gain from transient!)
model = fit_dynamic_transfer_function(
    dc_x=dc_x,
    dc_y=dc_y,
    transient_time=time,
    transient_voltage=transient_voltage,
    input_step_size=1.0
)

print("=" * 80)
print("RESULTS")
print("=" * 80)
print()

# Check results
dc_gain_fitted = model['combined_params'].get('dc_gain')
dc_gain_source = model['combined_params'].get('dc_gain_source')
bandwidth = model['combined_params'].get('bandwidth')
time_constant = model['combined_params'].get('time_constant')

print(f"Model Type: {model['model_type']}")
print(f"Intent: {model['intent']}")
print()

print("DC Gain:")
print(f"  Value: {dc_gain_fitted:.3f}")
print(f"  Source: {dc_gain_source}")
print(f"  Expected: {dc_gain_true:.3f}")
print(f"  Error: {abs(dc_gain_fitted - dc_gain_true)/dc_gain_true * 100:.1f}%")
print()

print("Dynamics:")
print(f"  Bandwidth: {bandwidth/1e6:.1f} MHz")
print(f"  Time Constant: {time_constant*1e9:.2f} ns (expected: {tau*1e9:.2f} ns)")
print()

print("Transfer Function:")
print(f"  {model['combined_params'].get('transfer_function')}")
print()

# Verify success criteria
success = True
if dc_gain_source != 'transient':
    print("✗ FAIL: DC gain source should be 'transient'")
    success = False
else:
    print("✓ PASS: DC gain extracted from transient (ring oscillator compatible!)")

if abs(dc_gain_fitted - dc_gain_true) / dc_gain_true > 0.05:
    print(f"✗ FAIL: DC gain error too high ({abs(dc_gain_fitted - dc_gain_true)/dc_gain_true * 100:.1f}%)")
    success = False
else:
    print("✓ PASS: DC gain accurate")

if model['combined_params'].get('model_class') != 'first_order_lag':
    print(f"✗ FAIL: Model class should be 'first_order_lag', got '{model['combined_params'].get('model_class')}'")
    success = False
else:
    print("✓ PASS: Full dynamic model created")

print()
if success:
    print("✅ ALL TESTS PASSED - Ring oscillator handling works!")
else:
    print("❌ SOME TESTS FAILED")

print("=" * 80)
