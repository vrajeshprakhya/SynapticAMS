# Transient-Based gm/gds Extraction - Quick Start

## What Was Implemented

A new method `extract_ac_params_transient()` in `NgspiceRunner` that extracts small-signal parameters (gm, gds) using transient analysis with AC perturbation instead of the standard `.OP` analysis.

## Why Use This?

- **Validation**: Cross-check results from standard `.OP + show` method
- **Troubleshooting**: Works when DC operating point analysis has convergence issues
- **Understanding**: Transparent calculation showing exactly how parameters are measured
- **Flexibility**: Easy to modify for custom bias conditions or test frequencies

## Quick Example

```python
from ngspice_runner import NgspiceRunner

# Your device model
netlist = """
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

runner = NgspiceRunner()

# Extract gm and gds at Vgs=0.9V, Vds=1.8V
params = runner.extract_ac_params_transient(
    netlist,
    device_name='M1',
    vg_dc=0.9,
    vd_dc=1.8
)

print(f"gm  = {params['gm']:.3e} S")
print(f"gds = {params['gds']:.3e} S")
print(f"Intrinsic gain = {params['gm']/params['gds']:.1f}")
```

## Test Results

Run the validation test:
```bash
cd ~/SynapticAMS
python3 test_transient_gm_gds.py
```

Expected output: Transient method matches `.OP` method within 0.5% for NMOS devices.

## Files Modified/Created

1. **ngspice_runner.py** (lines 1137-1400)
   - `extract_ac_params_transient()` - main method
   - `_parse_single_device()` - extract device info from netlist
   - `_measure_gm_transient()` - gm extraction
   - `_measure_gds_transient()` - gds extraction
   - `_build_transient_perturbation_deck()` - SPICE deck builder

2. **test_transient_gm_gds.py** (new file)
   - Comprehensive validation tests
   - Compares transient vs .OP methods
   - Tests frequency dependence
   - NMOS and PMOS test cases

3. **docs/TRANSIENT_PARAM_EXTRACTION.md** (new file)
   - Complete documentation
   - Theory and implementation details
   - Usage examples
   - Parameter selection guide

## How It Works (Simplified)

1. **Build test circuit**: Creates a simple circuit with the device and bias sources
2. **Inject AC perturbation**: Adds small SIN source (default 10mV @ 1MHz) to gate or drain
3. **Run transient simulation**: Simulates 5 periods of the AC signal
4. **Extract amplitude**: Measures peak-to-peak current variation
5. **Calculate parameter**: gm = ΔI/ΔV or gds = ΔI/ΔV

## Method Comparison

| Feature              | .OP + show          | Transient + Perturbation |
|----------------------|---------------------|--------------------------|
| Speed                | Fast (~0.1s)        | Slower (~1-2s)          |
| Accuracy             | Excellent           | Good (±0.5%)            |
| DC convergence       | Required            | More forgiving          |
| Transparency         | Black box           | Explicit calculation    |
| Frequency dependency | N/A                 | Can test at different f |
| PMOS support         | ✓ Full              | ⚠️ Partial (needs work)  |

## When to Use Which Method

**Use standard .OP method when:**
- You need maximum speed
- Circuit converges reliably
- You're in production flow

**Use transient method when:**
- Validating critical designs
- DC convergence is problematic
- You want to understand the extraction
- Teaching or debugging

## Advanced Options

```python
params = runner.extract_ac_params_transient(
    netlist, 'M1',
    vg_dc=0.9,              # Gate DC bias (V)
    vd_dc=1.8,              # Drain DC bias (V)
    perturbation_mv=10.0,   # AC amplitude (mV) - default 10
    freq_hz=1e6,            # Test frequency (Hz) - default 1MHz
    n_periods=5             # Number of periods - default 5
)
```

## Current Limitations

1. **NMOS-focused**: Best results with source-grounded NMOS. PMOS needs topology improvements.
2. **Single device**: Extracts one device at a time (rebuilds circuit each time).
3. **Simple models**: Tested with LEVEL=1. Higher-level models (BSIM, etc.) should work but need validation.

## Next Steps

To extend this implementation:

1. **Add FFT extraction**: Replace peak detection with FFT for better noise immunity
2. **Support PMOS**: Fix test circuit topology for PMOS devices
3. **Multi-device**: Batch extraction from existing circuit
4. **Add Cgd/Cgs**: Frequency sweep to extract capacitances
5. **Auto-bias**: Parse netlist to find existing DC bias instead of manual specification

## Questions?

Check the full documentation: `docs/TRANSIENT_PARAM_EXTRACTION.md`
