#!/usr/bin/env python3
"""
transient_analysis_utils.py

Utilities for analyzing transient simulation data:
- Oscillation frequency extraction
- Zero-crossing detection
- FFT analysis
- Amplitude measurement
"""

import numpy as np
from typing import Dict, Optional, Tuple


def extract_oscillation_frequency(time: np.ndarray, voltage: np.ndarray,
                                   method: str = 'zero_crossing') -> Optional[float]:
    """
    Extract oscillation frequency from transient waveform.

    Args:
        time: Time array (seconds)
        voltage: Voltage array (volts)
        method: 'zero_crossing' | 'fft' | 'autocorrelation'

    Returns:
        float: Oscillation frequency in Hz, or None if not oscillating
    """
    if len(time) < 10 or len(voltage) < 10:
        return None

    if method == 'zero_crossing':
        return _frequency_from_zero_crossings(time, voltage)
    elif method == 'fft':
        return _frequency_from_fft(time, voltage)
    elif method == 'autocorrelation':
        return _frequency_from_autocorrelation(time, voltage)
    else:
        raise ValueError(f"Unknown method: {method}")


def _frequency_from_zero_crossings(time: np.ndarray, voltage: np.ndarray) -> Optional[float]:
    """
    Extract frequency by counting zero crossings.

    More robust than FFT for noisy signals.
    """
    # Remove DC offset
    voltage_centered = voltage - np.mean(voltage)

    # Find rising edge zero crossings
    crossings = []
    for i in range(1, len(voltage_centered)):
        if voltage_centered[i-1] < 0 and voltage_centered[i] >= 0:
            # Linear interpolation for exact crossing time
            t_cross = time[i-1] + (time[i] - time[i-1]) * (
                -voltage_centered[i-1] / (voltage_centered[i] - voltage_centered[i-1])
            )
            crossings.append(t_cross)

    if len(crossings) < 2:
        return None  # Not enough crossings

    # Calculate periods between consecutive crossings
    periods = np.diff(crossings)

    # Check if signal is periodic (standard deviation < 10% of mean)
    if len(periods) < 3:
        return None

    mean_period = np.mean(periods)
    std_period = np.std(periods)

    if std_period / mean_period > 0.10:  # More than 10% variation
        return None  # Not consistently oscillating

    return 1.0 / mean_period if mean_period > 0 else None


def _frequency_from_fft(time: np.ndarray, voltage: np.ndarray) -> Optional[float]:
    """
    Extract frequency using FFT (Fast Fourier Transform).

    Most accurate for clean sinusoidal signals.
    """
    # Remove DC component
    voltage_ac = voltage - np.mean(voltage)

    # Compute FFT
    fft_result = np.fft.fft(voltage_ac)
    frequencies = np.fft.fftfreq(len(time), time[1] - time[0])

    # Only positive frequencies
    pos_mask = frequencies > 0
    pos_freqs = frequencies[pos_mask]
    pos_magnitudes = np.abs(fft_result[pos_mask])

    if len(pos_magnitudes) == 0:
        return None

    # Find peak frequency (ignoring DC)
    peak_idx = np.argmax(pos_magnitudes)
    peak_freq = pos_freqs[peak_idx]
    peak_magnitude = pos_magnitudes[peak_idx]

    # Check if peak is significant (> 10% of max)
    if peak_magnitude < 0.1 * np.max(pos_magnitudes):
        return None

    return float(peak_freq)


def _frequency_from_autocorrelation(time: np.ndarray, voltage: np.ndarray) -> Optional[float]:
    """
    Extract frequency using autocorrelation.

    Good for noisy periodic signals.
    """
    # Remove DC
    voltage_ac = voltage - np.mean(voltage)

    # Compute autocorrelation
    autocorr = np.correlate(voltage_ac, voltage_ac, mode='full')
    autocorr = autocorr[len(autocorr)//2:]  # Keep only positive lags

    # Normalize
    autocorr = autocorr / autocorr[0]

    # Find first minimum (end of first period)
    min_idx = np.argmin(autocorr[1:100]) + 1  # Search in first 100 samples

    # Find second peak (after one period)
    peak_idx = np.argmax(autocorr[min_idx:]) + min_idx

    if peak_idx <= 1:
        return None

    # Period in samples
    period_samples = peak_idx
    dt = time[1] - time[0]
    period_time = period_samples * dt

    return 1.0 / period_time if period_time > 0 else None


def measure_amplitude(voltage: np.ndarray, method: str = 'peak_to_peak') -> float:
    """
    Measure signal amplitude.

    Args:
        voltage: Voltage array
        method: 'peak_to_peak' | 'rms' | 'peak'

    Returns:
        float: Amplitude in volts
    """
    if method == 'peak_to_peak':
        return float(np.max(voltage) - np.min(voltage))
    elif method == 'rms':
        return float(np.sqrt(np.mean(voltage**2)))
    elif method == 'peak':
        voltage_centered = voltage - np.mean(voltage)
        return float(np.max(np.abs(voltage_centered)))
    else:
        raise ValueError(f"Unknown method: {method}")


def detect_oscillation(time: np.ndarray, voltage: np.ndarray,
                       min_cycles: int = 3,
                       min_amplitude: float = 0.01) -> bool:
    """
    Detect if a signal is oscillating.

    Args:
        time: Time array
        voltage: Voltage array
        min_cycles: Minimum number of cycles to consider oscillation
        min_amplitude: Minimum peak-to-peak amplitude (volts)

    Returns:
        bool: True if oscillating, False otherwise
    """
    # Check amplitude
    amplitude = measure_amplitude(voltage, 'peak_to_peak')
    if amplitude < min_amplitude:
        return False

    # Try to extract frequency
    freq = extract_oscillation_frequency(time, voltage, 'zero_crossing')
    if freq is None:
        return False

    # Check if we have enough cycles in the data
    total_time = time[-1] - time[0]
    num_cycles = freq * total_time

    return num_cycles >= min_cycles


def characterize_oscillator(time: np.ndarray, voltage: np.ndarray,
                            skip_transient: float = 0.2) -> Dict:
    """
    Fully characterize an oscillator waveform.

    Args:
        time: Time array (seconds)
        voltage: Voltage array (volts)
        skip_transient: Fraction of data to skip for startup transient (0-1)

    Returns:
        dict: {
            'is_oscillating': bool,
            'frequency': float (Hz),
            'period': float (seconds),
            'amplitude': float (peak-to-peak volts),
            'dc_offset': float (volts),
            'waveform_type': 'sine' | 'square' | 'triangle' | 'unknown'
        }
    """
    # Skip initial transient
    skip_samples = int(len(time) * skip_transient)
    time_steady = time[skip_samples:]
    voltage_steady = voltage[skip_samples:]

    result = {
        'is_oscillating': False,
        'frequency': None,
        'period': None,
        'amplitude': 0.0,
        'dc_offset': 0.0,
        'waveform_type': 'unknown'
    }

    # Check if oscillating
    if not detect_oscillation(time_steady, voltage_steady):
        return result

    result['is_oscillating'] = True

    # Extract frequency (try multiple methods)
    freq_zc = extract_oscillation_frequency(time_steady, voltage_steady, 'zero_crossing')
    freq_fft = extract_oscillation_frequency(time_steady, voltage_steady, 'fft')

    # Use most reliable
    if freq_zc and freq_fft:
        result['frequency'] = (freq_zc + freq_fft) / 2  # Average
    elif freq_zc:
        result['frequency'] = freq_zc
    elif freq_fft:
        result['frequency'] = freq_fft
    else:
        result['is_oscillating'] = False
        return result

    result['period'] = 1.0 / result['frequency']

    # Measure amplitude and DC offset
    result['amplitude'] = measure_amplitude(voltage_steady, 'peak_to_peak')
    result['dc_offset'] = float(np.mean(voltage_steady))

    # Classify waveform type
    result['waveform_type'] = _classify_waveform(voltage_steady)

    return result


def _classify_waveform(voltage: np.ndarray) -> str:
    """
    Classify waveform as sine, square, triangle, or unknown.

    Uses harmonic content analysis.
    """
    # FFT analysis
    voltage_ac = voltage - np.mean(voltage)
    fft_result = np.abs(np.fft.fft(voltage_ac))

    # Get first 10 harmonics
    n_harmonics = min(10, len(fft_result) // 2)
    harmonics = fft_result[1:n_harmonics+1]

    if len(harmonics) < 3:
        return 'unknown'

    # Normalize
    harmonics = harmonics / harmonics[0]

    # Sine wave: only fundamental (low harmonics)
    if np.sum(harmonics[1:]) / harmonics[0] < 0.2:
        return 'sine'

    # Square wave: strong odd harmonics (1, 3, 5, ...)
    odd_energy = np.sum(harmonics[1::2])
    even_energy = np.sum(harmonics[2::2])
    if odd_energy > 2 * even_energy:
        return 'square'

    # Triangle wave: very strong odd harmonics, falling as 1/n²
    if len(harmonics) >= 5:
        # Check if 3rd harmonic is ~1/9 of fundamental
        if 0.05 < harmonics[2] < 0.15:
            return 'triangle'

    return 'unknown'


# Example usage
if __name__ == "__main__":
    # Test with synthetic oscillator data
    t = np.linspace(0, 1e-6, 1000)  # 1 microsecond
    f = 1e6  # 1 MHz
    v = 2.5 + 1.5 * np.sin(2 * np.pi * f * t)  # 2.5V DC offset, 1.5V amplitude

    result = characterize_oscillator(t, v, skip_transient=0.1)

    print("Oscillator Characterization:")
    print(f"  Is oscillating: {result['is_oscillating']}")
    print(f"  Frequency:      {result['frequency']/1e6:.3f} MHz")
    print(f"  Period:         {result['period']*1e9:.3f} ns")
    print(f"  Amplitude:      {result['amplitude']:.3f} V (peak-to-peak)")
    print(f"  DC offset:      {result['dc_offset']:.3f} V")
    print(f"  Waveform type:  {result['waveform_type']}")
