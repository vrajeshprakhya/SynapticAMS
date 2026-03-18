"""
Oscillator-Specific Equivalence Checking

For oscillators, traditional point-by-point comparison fails because:
- Phase alignment issues
- Waveform shape differences (sine vs complex)
- Startup transients

Instead, we use frequency-domain metrics:
- Frequency matching
- Amplitude (RMS or peak-to-peak)
- DC offset
"""

import numpy as np
from scipy import signal as scipy_signal
from dataclasses import dataclass

@dataclass
class OscillatorEquivalenceResult:
    passed: bool
    frequency_error: float        # Hz
    frequency_error_pct: float    # %
    amplitude_error: float        # V
    amplitude_error_pct: float    # %
    offset_error: float           # V
    spice_frequency: float        # Hz
    vams_frequency: float         # Hz
    spice_amplitude: float        # V
    vams_amplitude: float         # V
    spice_offset: float           # V
    vams_offset: float            # V


def extract_oscillator_params(time, voltage):
    """
    Extract frequency, amplitude, and offset from oscillating waveform.
    
    Returns:
        dict: {'frequency', 'amplitude', 'offset', 'rms'}
    """
    # DC offset
    offset = np.mean(voltage)
    v_ac = voltage - offset
    
    # RMS amplitude
    rms = np.sqrt(np.mean(v_ac**2))
    
    # Peak-to-peak amplitude
    amplitude = np.ptp(voltage) / 2
    
    # Frequency from zero crossings
    zero_crossings = np.where(np.diff(np.sign(v_ac)))[0]
    if len(zero_crossings) >= 4:
        # Use zero crossings to find period
        half_periods = np.diff(time[zero_crossings])
        # Full period is 2x half-period
        n_pairs = len(half_periods) // 2
        if n_pairs > 0:
            periods = half_periods[:n_pairs*2:2] + half_periods[1:n_pairs*2:2]
            period = np.median(periods)
            frequency = 1.0 / period if period > 0 else 0.0
        else:
            periods = half_periods * 2
            frequency = 1.0 / np.median(periods) if len(periods) > 0 else 0.0
    else:
        frequency = 0.0
    
    return {
        'frequency': frequency,
        'amplitude': amplitude,
        'rms': rms,
        'offset': offset
    }


def check_oscillator_equivalence(spice_time, spice_voltage, vams_time, vams_voltage,
                                 freq_tol=0.1, amp_tol=0.2, offset_tol=0.2):
    """
    Check equivalence between two oscillating signals using frequency-domain metrics.
    
    Args:
        spice_time: SPICE time array
        spice_voltage: SPICE voltage array
        vams_time: VAMS time array  
        vams_voltage: VAMS voltage array
        freq_tol: Frequency tolerance (fraction, default 10%)
        amp_tol: Amplitude tolerance (fraction, default 20%)
        offset_tol: Offset tolerance (V, default 0.2V)
    
    Returns:
        OscillatorEquivalenceResult
    """
    # Extract parameters from both waveforms
    spice_params = extract_oscillator_params(spice_time, spice_voltage)
    vams_params = extract_oscillator_params(vams_time, vams_voltage)
    
    # Compute errors
    freq_error = abs(spice_params['frequency'] - vams_params['frequency'])
    freq_error_pct = freq_error / spice_params['frequency'] * 100 if spice_params['frequency'] > 0 else 0
    
    amp_error = abs(spice_params['amplitude'] - vams_params['amplitude'])
    amp_error_pct = amp_error / spice_params['amplitude'] * 100 if spice_params['amplitude'] > 0 else 0
    
    offset_error = abs(spice_params['offset'] - vams_params['offset'])
    
    # Pass/fail criteria
    freq_match = freq_error_pct <= (freq_tol * 100)
    amp_match = amp_error_pct <= (amp_tol * 100)
    offset_match = offset_error <= offset_tol
    
    passed = freq_match and amp_match and offset_match
    
    return OscillatorEquivalenceResult(
        passed=passed,
        frequency_error=freq_error,
        frequency_error_pct=freq_error_pct,
        amplitude_error=amp_error,
        amplitude_error_pct=amp_error_pct,
        offset_error=offset_error,
        spice_frequency=spice_params['frequency'],
        vams_frequency=vams_params['frequency'],
        spice_amplitude=spice_params['amplitude'],
        vams_amplitude=vams_params['amplitude'],
        spice_offset=spice_params['offset'],
        vams_offset=vams_params['offset']
    )
