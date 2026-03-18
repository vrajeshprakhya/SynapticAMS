# Transient-Based Small-Signal Parameter Extraction

## Overview

This document describes the transient-based AC perturbation method for extracting small-signal parameters (gm, gds) from SPICE devices, implemented as an alternative to the standard `.OP + show` approach.

## Background

### Standard Method (.OP + show)
The existing `extract_ac_params()` method uses ngspice's built-in operating point analysis:

```python
runner = NgspiceRunner()
params = runner.extract_ac_params(netlist, ['M1'])
# Returns: {'M1': {'gm': value, 'gds': value, 'gmb': value}}
```

**Advantages:**
- Fast (single `.op` analysis)
- Direct access to ngspice's internal device models
- Well-tested and reliable

**Limitations:**
- Requires successful DC convergence
- Black-box (can't verify calculation method)
- Limited to devices supported by ngspice's `show` command

### Transient Method (AC Perturbation)
The new `extract_ac_params_transient()` method uses time-domain simulation with small AC perturbations:

```python
runner = NgspiceRunner()
params = runner.extract_ac_params_transient(
    netlist, 'M1',
    vg_dc=0.9,  # Gate bias
    vd_dc=1.8,  # Drain bias
    perturbation_mv=10.0,  # 10 mV AC signal
    freq_hz=1e6,           # 1 MHz test frequency
    n_periods=5            # Simulate 5 periods
)
# Returns: {'gm': value, 'gds': value, 'vg_dc': 0.9, 'vd_dc': 1.8, ...}
```

**Advantages:**
- Works when DC convergence is difficult
- Transparent calculation (measure ΔI/ΔV directly)
- Can be extended to include parasitic effects
- Useful for validation and debugging

**Limitations:**
- Slower (requires full transient simulation)
- More complex setup
- Currently limited to simple NMOS devices (PMOS support needs work)

## How It Works

### Theory

Small-signal parameters are defined as partial derivatives at the DC operating point:

- **gm (transconductance)**: ∂I_d/∂V_gs at constant V_ds
- **gds (output conductance)**: ∂I_d/∂V_ds at constant V_gs

The transient method approximates these derivatives by applying small AC perturbations:

1. **For gm extraction:**
   - Set DC bias: V_gs = vg_dc, V_ds = vd_dc
   - Apply small AC signal to gate: V_g = vg_dc + ΔV·sin(ωt)
   - Measure AC component of drain current: I_d ≈ I_dc + ΔI·sin(ωt)
   - Calculate: gm ≈ ΔI / ΔV

2. **For gds extraction:**
   - Set DC bias: V_gs = vg_dc, V_ds = vd_dc
   - Apply small AC signal to drain: V_d = vd_dc + ΔV·sin(ωt)
   - Measure AC component of drain current: I_d ≈ I_dc + ΔI·sin(ωt)
   - Calculate: gds ≈ ΔI / ΔV

### Implementation

The method builds custom test circuits for each measurement:

**gm test circuit:**
```
Vg_dc: vg_dc ─── gate_drive
                     │
Vpert_gm: SIN    [gate] ─── M1 ─── Vmeas_drain ─── vd_dc
                             │
                           [source]
                             │
                            GND
```

**gds test circuit:**
```
Vg_dc: vg_dc ─── [gate] ─── M1 ─── Vmeas_drain ─── vd_pert ─── vd_dc
                             │                          │
                          [source]                  Vpert_gds: SIN
                             │
                            GND
```

## Validation Results

Test results from `test_transient_gm_gds.py`:

### NMOS Extraction Accuracy

| Vgs (V) | Vds (V) | gm_OP (S)   | gm_tran (S) | Error | Region             |
|---------|---------|-------------|-------------|-------|--------------------|
| 0.50    | 1.80    | 1.036e-04   | 1.036e-04   | 0.0%  | subthreshold       |
| 0.70    | 1.80    | 3.108e-04   | 3.108e-04   | 0.0%  | weak inversion     |
| 0.90    | 1.80    | 5.180e-04   | 5.179e-04   | 0.0%  | moderate inversion |
| 1.20    | 1.80    | 8.288e-04   | 8.287e-04   | 0.0%  | strong inversion   |
| 0.90    | 0.50    | 5.050e-04   | 5.024e-04   | 0.5%  | linear region      |

**Conclusion:** The transient method matches the .OP method within 0.5% for NMOS devices across all operating regions.

### Frequency Independence

For a LEVEL=1 MOSFET model without parasitics, gm and gds are independent of frequency (quasi-static approximation):

| Frequency | gm (S)      | gds (S)     |
|-----------|-------------|-------------|
| 1 kHz     | 5.179e-04   | 2.500e-06   |
| 10 kHz    | 5.179e-04   | 2.500e-06   |
| 100 kHz   | 5.179e-04   | 2.500e-06   |
| 1 MHz     | 5.179e-04   | 2.500e-06   |
| 10 MHz    | 5.179e-04   | 2.500e-06   |
| 100 MHz   | 5.179e-04   | 2.500e-06   |

This validates that the AC extraction is working correctly at the small-signal level.

## Usage Examples

### Basic Usage

```python
from ngspice_runner import NgspiceRunner

# Define device model
netlist = """
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

runner = NgspiceRunner()

# Extract gm/gds at specific bias point
params = runner.extract_ac_params_transient(
    netlist, 'M1',
    vg_dc=0.9,   # 0.9V gate voltage
    vd_dc=1.8,   # 1.8V drain voltage
    perturbation_mv=10.0,
    freq_hz=1e6,
    n_periods=5
)

print(f"gm  = {params['gm']:.3e} S")
print(f"gds = {params['gds']:.3e} S")
print(f"Output resistance ro = {1/params['gds']:.1f} Ω")
print(f"Intrinsic gain Av = gm/gds = {params['gm']/params['gds']:.1f}")
```

### Sweeping Bias Points

```python
import numpy as np
import matplotlib.pyplot as plt

# Sweep Vgs from 0.4V to 1.4V
vgs_values = np.linspace(0.4, 1.4, 20)
gm_values = []

for vgs in vgs_values:
    params = runner.extract_ac_params_transient(
        netlist, 'M1',
        vg_dc=vgs,
        vd_dc=1.8
    )
    gm_values.append(params['gm'])

plt.plot(vgs_values, gm_values)
plt.xlabel('Vgs (V)')
plt.ylabel('gm (S)')
plt.title('Transconductance vs Gate Voltage')
plt.grid(True)
plt.savefig('gm_vs_vgs.png')
```

### Comparing Methods

```python
# Standard .OP method
netlist_full = """
M1 vd vg 0 0 NMOS W=10u L=1u
VDD vd 0 DC 1.8
Vin vg 0 DC 0.9
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
"""

params_op = runner.extract_ac_params(netlist_full, ['M1'])
gm_op = params_op['M1']['gm']

# Transient method
netlist_model = """
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
"""

params_tran = runner.extract_ac_params_transient(
    netlist_model, 'M1',
    vg_dc=0.9, vd_dc=1.8
)
gm_tran = params_tran['gm']

# Compare
print(f"gm (.OP method):      {gm_op:.3e} S")
print(f"gm (transient):       {gm_tran:.3e} S")
print(f"Relative difference:  {abs(gm_tran-gm_op)/gm_op*100:.2f}%")
```

## Parameter Selection Guide

### Perturbation Amplitude
- **Default: 10 mV** (good for most cases)
- Too small (<1 mV): Noise may affect results
- Too large (>50 mV): Nonlinear effects, not truly "small signal"
- Rule of thumb: Use 1-2% of the DC voltage range

### Frequency
- **Default: 1 MHz** (good for MOSFET small-signal analysis)
- Too low (<1 kHz): Simulation takes long time
- Too high (>100 MHz): Parasitic capacitances affect results
- For models with parasitics (BSIM, etc.): Use 100 kHz - 10 MHz

### Number of Periods
- **Default: 5** (good compromise)
- Minimum: 3 (need enough data for amplitude extraction)
- More periods: Better accuracy but slower simulation
- Use second half of waveform to avoid transient effects

## Known Limitations

1. **PMOS devices**: Current implementation works best for NMOS with source at ground. PMOS circuits with source at VDD need topology adjustments.

2. **Complex circuits**: The method builds simplified test circuits. For extracting parameters from devices embedded in complex circuits, use the `.OP + show` method.

3. **Frequency-dependent effects**: The simple amplitude extraction assumes quasi-static operation. For accurate high-frequency characterization, AC analysis is more appropriate.

4. **Convergence**: While this method can work when DC convergence fails, the transient simulation still needs to converge for each time step.

## Future Enhancements

Potential improvements:

1. **FFT-based extraction**: Use FFT instead of peak detection for more accurate amplitude measurement in noisy signals

2. **Multi-device support**: Extract parameters from multiple devices in a single netlist without rebuilding circuits

3. **PMOS support**: Handle PMOS topologies correctly

4. **Gmb extraction**: Add body-effect transconductance (∂I_d/∂V_bs) measurement

5. **Capacitance extraction**: Extend to extract Cgs, Cgd, etc. using frequency sweep

6. **Automatic bias detection**: Parse existing netlist to extract DC bias instead of requiring manual specification

## References

1. Razavi, B. "Design of Analog CMOS Integrated Circuits" (2nd ed.), Section 2.2: Small-Signal Model
2. Gray, Hurst, et al. "Analysis and Design of Analog Integrated Circuits" (5th ed.), Section 1.5: Small-Signal Analysis
3. ngspice User Manual, Section 11.3.3: Transient Analysis (.TRAN)
4. ngspice User Manual, Section 13.5: SHOW command

## Related Files

- Implementation: `ngspice_runner.py` lines 1137-1400
- Test script: `test_transient_gm_gds.py`
- Standard method: `ngspice_runner.py` lines 1039-1080 (`extract_ac_params()`)
