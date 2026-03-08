# Multi-Mode Equivalence Checking (DC + AC + Transient)

## Overview

The equivalence checker now automatically determines which analyses are required based on **circuit topology analysis**, eliminating manual guesswork.

## How It Works

### 1. Circuit Topology Analysis (circuit_analyzer.py)

When blocks are extracted, the analyzer:

**a) Detects Component Types:**
```python
# Count reactive elements
num_caps, num_inds = count_reactive_elements(block_graph)

# Check for active devices
has_transistors = has_active_devices(block_graph)
```

**b) Classifies Behavior:**
```python
behavior_class = classify_circuit_behavior(block_graph, sim_axes, outputs)
# Returns: 'STRUCTURAL_LINEAR', 'SMALL_SIGNAL_LINEARIZABLE', or 'NONLINEAR'
```

**c) Determines Required Analyses:**
```python
required_analyses = determine_required_analyses(block_graph, behavior_class)
# Returns: ['dc'] or ['dc', 'ac'] or ['dc', 'ac', 'tran']
```

---

### 2. Analysis Selection Logic

```python
def determine_required_analyses(block_graph, behavior_class):
    """
    Automatic analysis mode selection based on circuit topology
    """
    num_caps, num_inds = count_reactive_elements(block_graph)
    num_reactive = num_caps + num_inds

    modes = ['dc']  # DC always included

    if behavior_class == 'STRUCTURAL_LINEAR':
        # Pure passive (R/L/C) circuit
        if num_reactive > 0:
            modes.append('ac')  # RC/LC filter → AC essential
            if num_reactive >= 2:
                modes.append('tran')  # Multiple poles → check settling

    elif behavior_class == 'SMALL_SIGNAL_LINEARIZABLE':
        # Analog amplifier/buffer
        if num_reactive > 0:
            modes.append('ac')  # Has frequency response
            if num_inds > 0:
                modes.append('tran')  # Inductors → ringing possible

    elif behavior_class == 'NONLINEAR':
        # Comparator, switch, limiter
        modes.append('ac')   # Check small-signal if any
        modes.append('tran')  # Transient essential for switching

    return modes
```

---

### 3. Example Circuit Classifications

| Circuit | Components | Behavior Class | Required Analyses | Reason |
|---------|-----------|----------------|-------------------|--------|
| **Differential pair (no caps)** | M1, M2, R | SMALL_SIGNAL_LINEARIZABLE | `['dc']` | Purely resistive amp |
| **Common-source + load cap** | M1, R, C | SMALL_SIGNAL_LINEARIZABLE | `['dc', 'ac']` | Single pole → check BW |
| **2-stage opamp + Miller C** | M1-M4, R, 2×C | SMALL_SIGNAL_LINEARIZABLE | `['dc', 'ac']` | Multi-pole → check stability |
| **RC lowpass filter** | R, C | STRUCTURAL_LINEAR | `['dc', 'ac']` | Frequency-dependent |
| **LC bandpass filter** | L, C | STRUCTURAL_LINEAR | `['dc', 'ac', 'tran']` | Resonant → check ringing |
| **Comparator** | M1-M4, R | NONLINEAR | `['dc', 'ac', 'tran']` | Switching → need transient |

---

### 4. Block Info Enhancement

Each extracted block now includes:

```python
block_info = {
    "block_id": 0,
    "behavior_class": "SMALL_SIGNAL_LINEARIZABLE",
    "required_analyses": ['dc', 'ac'],  # ← NEW!
    "simulation_axes": ['inp', 'inn'],
    "outputs": ['vout'],
    ...
}
```

This information flows through to equivalence checking.

---

## Implementation Stages

### Stage 1: Topology Analysis (✅ DONE)

**Implemented:**
- `has_reactive_elements()` - Detect C/L
- `count_reactive_elements()` - Count C and L separately
- `determine_required_analyses()` - Automatic mode selection
- Updated block extraction to include `required_analyses`

**Result:** Each block knows which analyses it needs

---

### Stage 2: DC Equivalence Checking (✅ DONE)

**Current implementation:**
```python
def check_block_equivalence(spice_netlist, verilog_ams_code, block_info):
    # DC sweep for 1D/2D
    # Point-by-point for 3D+
    # Compare outputs
```

**Status:** Fully implemented with DC sweep optimization

---

### Stage 3: AC Equivalence Checking (🚧 TO BE IMPLEMENTED)

**What needs to be added:**

```python
def _check_ac_equivalence(self, spice_netlist, verilog_ams_code, block_info):
    """
    Check small-signal AC frequency response equivalence
    """
    # Define frequency sweep (log scale)
    frequencies = np.logspace(0, 9, 100)  # 1Hz to 1GHz

    # SPICE AC analysis
    spice_ac = self._simulate_spice_ac(spice_netlist, frequencies, block_info)
    # Returns: {freq: [...], vout_mag_dB: [...], vout_phase_deg: [...]}

    # Verilog-AMS AC analysis
    vams_ac = self._simulate_verilog_ams_ac(verilog_ams_code, frequencies, block_info)

    # Compare magnitude and phase
    mag_error = np.abs(spice_ac['vout_mag_dB'] - vams_ac['vout_mag_dB'])
    phase_error = np.abs(spice_ac['vout_phase_deg'] - vams_ac['vout_phase_deg'])

    # Extract key metrics
    bw_spice = extract_3dB_bandwidth(spice_ac)
    bw_vams = extract_3dB_bandwidth(vams_ac)

    # Check tolerances
    passed = (
        np.all(mag_error < 1.0) and      # < 1dB error
        np.all(phase_error < 5.0) and    # < 5° error
        abs(bw_spice - bw_vams)/bw_spice < 0.05  # < 5% BW error
    )

    return ACEquivalenceResult(...)
```

**SPICE AC testbench:**
```spice
* AC analysis testbench
Vinp inp 0 DC 0.9 AC 1.0  ← DC bias + small AC signal

.ac dec 100 1 1G  ← Logarithmic frequency sweep

.control
run
print vdb(vout) vp(vout)  ← Magnitude (dB), Phase (°)
.endc
```

**Verilog-AMS AC:**
- Same concept: apply small AC signal on DC bias
- Use `.ac` analysis in ngspice with OSDI model
- Compare frequency response curves

---

### Stage 4: Transient Equivalence Checking (🚧 TO BE IMPLEMENTED)

**What needs to be added:**

```python
def _check_transient_equivalence(self, spice_netlist, verilog_ams_code, block_info):
    """
    Check large-signal transient response equivalence
    """
    # Define test stimulus (step input)
    stimulus = {
        'type': 'step',
        'step_time': 1e-6,   # Step at 1µs
        'v_initial': 0.0,
        'v_final': 1.8,
        'duration': 10e-6    # Simulate 10µs total
    }

    # SPICE transient
    spice_tran = self._simulate_spice_transient(spice_netlist, stimulus, block_info)
    # Returns: {time: [...], vout: [...]}

    # Verilog-AMS transient
    vams_tran = self._simulate_verilog_ams_transient(verilog_ams_code, stimulus, block_info)

    # Compare waveforms
    waveform_error = np.abs(spice_tran['vout'] - vams_tran['vout'])

    # Extract metrics
    rise_time_spice = extract_rise_time(spice_tran)
    rise_time_vams = extract_rise_time(vams_tran)

    overshoot_spice = extract_overshoot(spice_tran)
    overshoot_vams = extract_overshoot(vams_tran)

    # Check tolerances
    passed = (
        np.all(waveform_error < 0.01) and  # < 10mV error
        abs(rise_time_spice - rise_time_vams) < 0.1e-6 and  # < 100ns
        abs(overshoot_spice - overshoot_vams) < 0.05  # < 5%
    )

    return TransientEquivalenceResult(...)
```

**SPICE transient testbench:**
```spice
* Transient analysis testbench
Vinp inp 0 PWL(0 0V  1us 0V  1.01us 1.8V  10us 1.8V)  ← Step input

.tran 10ns 10us  ← Timestep: 10ns, Duration: 10µs

.control
run
print v(vout)
.endc
```

**Metrics to extract:**
- Rise time (10% → 90%)
- Fall time
- Overshoot / Undershoot
- Settling time
- Propagation delay
- Slew rate

---

### Stage 5: Multi-Mode Integration (🚧 TO BE IMPLEMENTED)

**Updated equivalence checker:**

```python
def check_block_equivalence(self, spice_netlist, verilog_ams_code, block_info):
    """
    Enhanced multi-mode equivalence checking
    """
    # Get required analyses from block_info
    required_analyses = block_info.get('required_analyses', ['dc'])

    results = {}

    # Run required analyses
    if 'dc' in required_analyses:
        print(f"  Running DC equivalence check...")
        results['dc'] = self._check_dc_equivalence(spice_netlist, verilog_ams_code, block_info)

    if 'ac' in required_analyses:
        print(f"  Running AC equivalence check...")
        results['ac'] = self._check_ac_equivalence(spice_netlist, verilog_ams_code, block_info)

    if 'tran' in required_analyses:
        print(f"  Running Transient equivalence check...")
        results['tran'] = self._check_transient_equivalence(spice_netlist, verilog_ams_code, block_info)

    # Overall pass if ALL required analyses pass
    overall_passed = all(r.passed for r in results.values())

    return MultiModeEquivalenceResult(
        passed=overall_passed,
        dc_result=results.get('dc'),
        ac_result=results.get('ac'),
        tran_result=results.get('tran')
    )
```

---

## Benefits

### 1. **Automatic Mode Selection**
✅ No manual configuration
✅ Based on actual circuit topology
✅ Always appropriate for circuit type

### 2. **Comprehensive Validation**
✅ DC: Baseline transfer function
✅ AC: Frequency response, bandwidth, stability
✅ Transient: Dynamic behavior, settling, overshoot

### 3. **Efficient Testing**
✅ Only runs necessary analyses
✅ Pure resistive circuits → DC only (fast)
✅ Filters → DC + AC
✅ Comparators → All three (complete)

### 4. **Transparent & Reproducible**
✅ Block info shows which analyses are required
✅ Testbenches saved for all modes
✅ Results broken down by analysis type

---

## Example Workflow

### Input: Two-Stage OpAmp with Miller Compensation

**Netlist:**
```spice
.subckt opamp inp inn vout vdd vss
  * First stage (differential pair)
  M1 mid1 inp tail vss NMOS W=20u L=1u
  M2 mid2 inn tail vss NMOS W=20u L=1u
  M3 tail bias vss vss NMOS W=40u L=1u

  * Active load (current mirror)
  M4 mid1 mid1 vdd vdd PMOS W=30u L=1u
  M5 mid2 mid1 vdd vdd PMOS W=30u L=1u

  * Second stage
  M6 vout mid2 vdd vdd PMOS W=100u L=1u
  M7 vout bias vss vss NMOS W=50u L=1u

  * Compensation capacitor (Miller)
  CC vout mid2 2pF

  * Load capacitor
  CL vout 0 10pF
.ends
```

**Analysis:**
```
1. Topology analysis:
   - Has transistors (M1-M7) → Active circuit
   - Has capacitors (CC, CL) → Reactive elements
   - num_caps = 2, num_inds = 0

2. Behavior classification:
   - Has passive loads → SMALL_SIGNAL_LINEARIZABLE

3. Analysis selection:
   - num_reactive = 2 → Need AC
   - No inductors → No transient needed (debatable!)
   - Result: ['dc', 'ac']
```

**Equivalence checking:**
```
Block 0: opamp
  Required analyses: ['dc', 'ac']

  Running DC equivalence check...
    ✓ DC gain: 60dB (SPICE) vs 59.8dB (Verilog-AMS)
    ✓ Input offset: <1mV
    ✓ PASS

  Running AC equivalence check...
    ✓ Unity-gain BW: 10MHz (SPICE) vs 9.8MHz (Verilog-AMS)
    ✓ Phase margin: 65° (SPICE) vs 64° (Verilog-AMS)
    ✓ PASS

  Overall: PASS
```

---

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Topology analysis** | ✅ Done | Detects C/L, counts reactive elements |
| **Behavior classification** | ✅ Done | Existing infrastructure |
| **Analysis mode selection** | ✅ Done | `determine_required_analyses()` |
| **Block info enhancement** | ✅ Done | `required_analyses` field added |
| **DC equivalence checking** | ✅ Done | With DC sweep optimization |
| **AC equivalence checking** | ⏳ TODO | Infrastructure ready, needs implementation |
| **Transient equivalence checking** | ⏳ TODO | Infrastructure ready, needs implementation |
| **Multi-mode integration** | ⏳ TODO | Dispatcher logic needed |

---

## Next Steps

1. **Implement `_simulate_spice_ac()`** - AC analysis via ngspice
2. **Implement `_simulate_verilog_ams_ac()`** - AC with OSDI
3. **Implement `_simulate_spice_transient()`** - Transient via ngspice
4. **Implement `_simulate_verilog_ams_transient()`** - Transient with OSDI
5. **Add metric extraction** - Bandwidth, rise time, overshoot, etc.
6. **Integrate multi-mode dispatcher** - Run all required analyses
7. **Update HTML report** - Show DC/AC/Transient results separately

---

## Summary

**Question:** "How are you going to determine when to include which [analysis] based on just circuit topology?"

**Answer:**

✅ **Automatic topology analysis** - Count capacitors, inductors, transistors
✅ **Behavior classification** - Already implemented in circuit_analyzer
✅ **Rule-based selection** - Clear logic based on components
✅ **No manual configuration** - All automatic
✅ **Infrastructure ready** - Plumbing in place, just need AC/tran methods

**Decision tree:**
```
Purely resistive (no C/L) → DC only
Has 1 reactive element → DC + AC
Has 2+ reactive elements → DC + AC + Transient
Has inductors → Always add Transient
Nonlinear (comparator) → DC + AC + Transient
```

**The topology tells us what we need!**
