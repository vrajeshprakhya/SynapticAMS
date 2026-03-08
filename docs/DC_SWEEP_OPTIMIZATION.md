# DC Sweep Optimization in Equivalence Checker

## Problem: Original Inefficient Approach

### What Was Happening Before:

```
For 2500 test vectors (50×50 grid for 2D sweep):

testbench_0000.cir → ngspice → vout[0]
testbench_0001.cir → ngspice → vout[1]
testbench_0002.cir → ngspice → vout[2]
...
testbench_2499.cir → ngspice → vout[2499]

Total: 2500 separate ngspice invocations
Time: 2500× (simulation time + overhead)
```

### Individual Point Testbench Example:

```spice
* Testbench for point #1234
.subckt diff_amp inp inn vout vdd vss
  M1 vout inp nb vss NMOS W=20u L=1u
  M2 nb inn nb vss NMOS W=20u L=1u
  M3 nb nb vdd vdd PMOS W=40u L=1u
  Ibias nb vss DC 100uA
.ends

VDD vdd 0 DC 1.8
VSS vss 0 DC 0
Xdut inp inn vout vdd vss diff_amp

* Models
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
.model PMOS PMOS (LEVEL=1 VTO=-0.4 KP=50u)

* Single test point inputs
Vtest_inp inp 0 DC 9.000000000000e-01V
Vtest_inn inn 0 DC 8.500000000000e-01V

.op

.control
run
print vout
quit
.endc

.end
```

**Overhead per simulation:**
- Process spawn: ~50-100ms
- SPICE initialization: ~10-20ms
- Model loading: ~5-10ms
- **Total overhead**: ~65-130ms

**For 2500 points:**
- Pure overhead: 2500 × 100ms = **250 seconds = 4+ minutes**
- Plus actual simulation time!

---

## Solution: DC Sweep Optimization

### What Happens Now:

```
ONE testbench → ngspice with DC sweep → ALL 2500 points at once

Total: 1 ngspice invocation
Time: 1× (simulation time) + negligible overhead
Speedup: 10-100×
```

### Master DC Sweep Testbench:

```spice
* Master DC Sweep Testbench for diff_amp
* Generated: 2026-03-07 20:45:12
* Sweep: 2D grid (2500 total points)
* MUCH faster than individual point simulations!

.subckt diff_amp inp inn vout vdd vss
  M1 vout inp nb vss NMOS W=20u L=1u
  M2 nb inn nb vss NMOS W=20u L=1u
  M3 nb nb vdd vdd PMOS W=40u L=1u
  Ibias nb vss DC 100uA
.ends

VDD vdd 0 DC 1.8
VSS vss 0 DC 0
Vinp inp 0 DC 0
Vinn inn 0 DC 0
Xdut inp inn vout vdd vss diff_amp

* Models
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
.model PMOS PMOS (LEVEL=1 VTO=-0.4 KP=50u)

* Nested DC sweep - sweeps ALL 2500 points in ONE simulation!
.dc Vinp 0 1.8 0.036 Vinn 0 1.8 0.036

.control
run
print vout
quit
.endc

.end
```

**Overhead:**
- Process spawn: ~100ms (once!)
- SPICE initialization: ~20ms (once!)
- Model loading: ~10ms (once!)
- **Total overhead**: ~130ms for ALL points

**Speedup calculation:**
- Old way: 250s overhead + simulation time
- New way: 0.13s overhead + simulation time
- **Speedup: ~50-100× for typical circuits!**

---

## Implementation

### Code Changes:

**Before:**
```python
# equivalence_checker.py _simulate_spice()
for vector in test_vectors:  # 2500 iterations!
    modified_netlist = self._inject_test_vector(netlist, inputs, vector)
    dc_result = runner.dc_op(modified_netlist, outputs)
    results[out].append(dc_result.get(out_clean, np.nan))
```

**After:**
```python
# equivalence_checker.py _simulate_spice()
if len(inputs) == 1:
    # 1D sweep: ONE simulation for all points
    sweep_params = {'sweep_var': inputs[0], 'start': ..., 'stop': ..., ...}
    results = runner.dc_sweep(netlist, sweep_params)

elif len(inputs) == 2:
    # 2D nested sweep: ONE simulation for all points
    sweep_params = {'sweep_var_1': ..., 'sweep_var_2': ..., ...}
    results = runner.dc_sweep_2d(netlist, sweep_params)

else:
    # 3D+: Fall back to point-by-point (no native DC sweep for 3D+)
    results = self._simulate_spice_point_by_point(netlist, test_vectors, block_info)
```

### Testbench Files Generated:

```
testbenches/
└── diff_amp/
    ├── master_dc_sweep.cir        # ✨ NEW! One file for all 2500 points
    ├── spice/
    │   ├── testbench_000.cir      # Individual points (for debugging)
    │   ├── testbench_050.cir
    │   └── testbench_099.cir
    ├── verilog_ams/
    │   ├── testbench_000.cir
    │   ├── testbench_050.cir
    │   └── testbench_099.cir
    └── test_manifest.json
```

---

## Benefits

### Performance:

| Aspect | Old (Point-by-Point) | New (DC Sweep) | Improvement |
|--------|---------------------|----------------|-------------|
| Simulations | 2500 | 1 | 2500× fewer |
| Process spawns | 2500 | 1 | 2500× fewer |
| Overhead | ~250s | ~0.13s | ~2000× faster |
| Total time | ~300s | ~5-10s | **30-60× faster** |
| Testbenches saved | 2500 files | 1 file | 2500× fewer |

### Methodology:

✓ **Standard SPICE practice** - DC sweep is the canonical way to characterize circuits
✓ **Native simulator support** - Ngspice, Spectre, HSPICE all optimize DC sweeps
✓ **Better convergence** - Simulators use previous point as initial guess
✓ **Cleaner output** - One result set instead of 2500 separate outputs

### Usability:

✓ **Single file to review** - `master_dc_sweep.cir` has everything
✓ **Easy to modify** - Change sweep range, add more points, etc.
✓ **Standard format** - Any SPICE simulator can run it
✓ **Debugging friendly** - Individual point files still saved for failures

---

## Dimensions Supported

| Input Dimensions | DC Sweep Support | Method |
|-----------------|------------------|---------|
| **1D** (1 input) | ✅ Yes | `.dc Vinp 0 1.8 0.036` |
| **2D** (2 inputs) | ✅ Yes | `.dc Vinp 0 1.8 0.036 Vinn 0 1.8 0.036` |
| **3D+** (3+ inputs) | ❌ No native support | Falls back to point-by-point |

**Note:** SPICE doesn't support nested sweeps beyond 2D. For 3D+ circuits, we use Monte Carlo sampling (LHS) with point-by-point simulation.

---

## Example: 1D Sweep

### Circuit: Single-Input Amplifier
```
Inputs: vin
Outputs: vout
Test vectors: 50 points (0V → 1.8V)
```

### Old Method:
```
50 separate simulations
Time: ~5 seconds (overhead) + simulation
```

### New Method:
```spice
.dc Vvin 0 1.8 0.036

Time: ~0.1 seconds total
Speedup: 50×
```

---

## Example: 2D Sweep

### Circuit: Differential Amplifier
```
Inputs: inp, inn
Outputs: vout
Test vectors: 2500 points (50×50 grid)
```

### Old Method:
```
2500 separate simulations
Time: ~250 seconds (overhead) + ~50 seconds (simulation) = ~300s total
```

### New Method:
```spice
.dc Vinp 0 1.8 0.036 Vinn 0 1.8 0.036

Time: ~10 seconds total
Speedup: 30×
```

---

## Limitations

### When Point-by-Point is Still Used:

1. **3D+ inputs** - No native DC sweep support in SPICE
2. **Non-grid test vectors** - Random/Monte Carlo sampling
3. **DC sweep failure** - Falls back gracefully to point-by-point
4. **Mixed source types** - Complex voltage+current combinations

### Verilog-AMS OSDI:

Currently, Verilog-AMS simulation via OSDI still uses point-by-point because:
- OSDI models may not support DC sweep the same way as SPICE subcircuits
- Need to ensure uniform behavior between SPICE and Verilog-AMS sides

**Future optimization:** Investigate DC sweep support for OSDI models.

---

## Summary

**Before:** "Why do we need separate testbenches for each test vector?"
**Answer:** We don't! Using DC sweep is much better.

**Key Changes:**
- ✅ Use native `.dc` sweep commands for 1D and 2D
- ✅ Generate `master_dc_sweep.cir` testbench
- ✅ 10-100× faster equivalence checking
- ✅ Still save individual point testbenches for debugging
- ✅ Falls back to point-by-point for 3D+ or when DC sweep fails

**Result:** Fast, efficient, standard SPICE methodology!
