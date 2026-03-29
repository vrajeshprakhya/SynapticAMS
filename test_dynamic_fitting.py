#!/usr/bin/env python3
"""
Test the new dynamic transfer function fitting that combines DC + transient
"""
import numpy as np
from pipeline_ext.fit_transfer_function import (
    fit_dynamic_transfer_function,
    analyze_step_response,
    fit_transfer_function
)

print("="*70)
print("TESTING DYNAMIC TRANSFER FUNCTION FITTING")
print("="*70)

# Test 1: Create simulated DC sweep data (amplifier with gain=5)
print("\n[Test 1] DC Sweep Data (Amplifier with gain=5)")
dc_x = np.linspace(0, 1.0, 20)  # Input voltage 0-1V
dc_y = 5 * dc_x + 0.1  # Output = 5*input + offset
print(f"  DC input range: {dc_x[0]:.2f}V to {dc_x[-1]:.2f}V")
print(f"  DC output range: {dc_y[0]:.2f}V to {dc_y[-1]:.2f}V")
print(f"  Expected DC gain: 5.0")

# Test 2: Create simulated transient step response (first-order with tau=1ns, gain=5)
print("\n[Test 2] Transient Step Response (tau=1ns, gain=5)")
time = np.linspace(0, 10e-9, 100)  # 0-10ns
tau = 1e-9  # 1ns time constant
input_step = 1.0  # 1V step
final_value = 5.0 * input_step + 0.1  # gain=5, offset=0.1
initial_value = 0.1
transient_voltage = initial_value + (final_value - initial_value) * (1 - np.exp(-time/tau))

print(f"  Time range: {time[0]*1e9:.2f}ns to {time[-1]*1e9:.2f}ns")
print(f"  Initial voltage: {transient_voltage[0]:.3f}V")
print(f"  Final voltage: {transient_voltage[-1]:.3f}V")
print(f"  Expected tau: {tau*1e9:.2f}ns")

# Test 3: Analyze step response alone
print("\n[Test 3] Step Response Analysis")
step_analysis = analyze_step_response(time, transient_voltage, input_step_size=input_step)
print(f"  Valid: {step_analysis['is_valid']}")
print(f"  DC gain (from transient): {step_analysis['dc_gain']:.2f}")
print(f"  Rise time: {step_analysis['rise_time']*1e9:.3f}ns")
print(f"  Time constant: {step_analysis['time_constant']*1e9:.3f}ns")
print(f"  Bandwidth: {step_analysis['bandwidth']/1e6:.1f}MHz")

# Test 4: DC-only fitting
print("\n[Test 4] DC-Only Fitting")
dc_model = fit_transfer_function(dc_x, dc_y)
print(f"  Model type: {dc_model['model_type']}")
print(f"  Intent: {dc_model['intent']}")
if dc_model['model_type'] == 'analytic' and dc_model['intent'] == 'linear':
    gain = dc_model['model']['regions'][0]['params']['a']
    print(f"  Fitted gain: {gain:.2f}")

# Test 5: Combined DC + Transient fitting (THE NEW FUNCTIONALITY!)
print("\n[Test 5] Combined DC + Transient Fitting (NEW!)")
combined_model = fit_dynamic_transfer_function(
    dc_x=dc_x,
    dc_y=dc_y,
    transient_time=time,
    transient_voltage=transient_voltage,
    input_step_size=input_step
)

print(f"  Model type: {combined_model['model_type']}")
print(f"  Intent: {combined_model['intent']}")
print(f"  Model class: {combined_model['combined_params']['model_class']}")
print(f"  DC gain: {combined_model['combined_params']['dc_gain']:.2f}")
print(f"  Bandwidth: {combined_model['combined_params']['bandwidth']/1e6:.1f}MHz")
print(f"  Time constant: {combined_model['combined_params']['time_constant']*1e9:.3f}ns")
print(f"  Transfer function: {combined_model['combined_params']['transfer_function']}")

# Test 6: Verify accuracy
print("\n[Test 6] Accuracy Check")
expected_gain = 5.0
expected_tau = 1e-9
fitted_gain = combined_model['combined_params']['dc_gain']
fitted_tau = combined_model['combined_params']['time_constant']
fitted_bw = combined_model['combined_params']['bandwidth']

gain_error = abs(fitted_gain - expected_gain) / expected_gain * 100
tau_error = abs(fitted_tau - expected_tau) / expected_tau * 100

print(f"  DC gain error: {gain_error:.1f}%")
print(f"  Time constant error: {tau_error:.1f}%")

if gain_error < 10 and tau_error < 20:
    print("\n✓ PASS: Combined fitting successfully extracted DC gain and dynamics!")
else:
    print("\n✗ FAIL: Fitting accuracy below expected thresholds")

print("="*70)
