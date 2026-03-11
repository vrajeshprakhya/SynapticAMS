# Minimal SERDES IP Design for SynapticAMS Pipeline Validation

## Design Date: 2026-03-10

---

## Overview

This document describes a **minimal SERDES (Serializer/Deserializer) IP** designed from validated analog blocks found in ngspice examples. The goal is to demonstrate the complete SynapticAMS SPICE-to-Verilog-AMS pipeline with a realistic mixed-signal system.

---

## Design Philosophy

- **Simplicity First:** Use only validated analog blocks
- **Transistor-Level:** All analog blocks use BJT/MOSFET models (no behavioral models)
- **Testable:** Each block independently testable via DC/TRAN/AC sweeps
- **Realistic:** Representative of actual SERDES architecture

---

## Architecture

### Block Diagram

```
TX PATH:
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Data In    │────>│  TX Differential │────>│  TX Output  │
│  (Digital)  │     │      Driver      │     │  (CML/LVDS) │
└─────────────┘     └──────────────────┘     └─────────────┘
                             ▲
                             │
                      ┌──────┴───────┐
                      │     VCO      │
                      │  (589 MHz)   │
                      └──────────────┘

CHANNEL:
TX Output ──────[ Transmission Line ]─────> RX Input

RX PATH:
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  RX Input   │────>│  RX Differential │────>│  Data Out   │
│  (CML/LVDS) │     │     Amplifier    │     │  (Digital)  │
└─────────────┘     └──────────────────┘     └─────────────┘
```

---

## Validated Analog Blocks

### 1. VCO (Voltage-Controlled Oscillator)
- **Source:** `~/eda_tools/ngspice/examples/xspice/pll/vco_sub.cir`
- **Type:** 7-stage differential ring oscillator (BSIM3 MOSFET)
- **Frequency:** 589.4 MHz (at Vcont = 1.5V)
- **Supply:** 3.3V
- **Status:** ✅ VALIDATED
- **Use Case:** Clock generation for both TX and RX

### 2. Differential Pair
- **Source:** `~/eda_tools/ngspice/examples/tclspice/tcl/diffpair.cir`
- **Type:** BJT differential pair with current mirror bias
- **Gain:** ~12.7 V/V differential
- **Output Swing:** 25.24V (±12V differential)
- **Supply:** ±12V
- **Status:** ✅ VALIDATED
- **Use Case:** RX input amplifier, TX driver

---

## Minimal SERDES Configuration

For initial validation, we implement a **3-block minimal SERDES**:

### Configuration A: Clock + TX + RX

**Components:**
1. **VCO** - Clock generation (589 MHz)
2. **TX Driver** - Differential output driver (re-use differential pair topology)
3. **RX Amplifier** - Differential input buffer (validated differential pair)

**Signal Path:**
```
Clock (VCO) ──┬──> TX Driver ──> [Channel] ──> RX Amplifier ──> Output
              │
              └──> RX Clock (optional CDR)
```

**Expected Behavior:**
- VCO generates 589 MHz clock
- TX Driver converts digital signal to differential CML output
- RX Amplifier recovers and amplifies differential signal
- Complete analog signal path demonstrated

---

## Implementation Plan

### Phase 1: Individual Block Netlists ✅ COMPLETE
- ✅ VCO subcircuit extracted (vco_sub.cir)
- ✅ Differential pair extracted (diffpair.cir)

### Phase 2: Integration Netlist (IN PROGRESS)
- [ ] Create top-level SERDES netlist
- [ ] Instantiate VCO for clock generation
- [ ] Instantiate TX driver (differential pair configured as driver)
- [ ] Instantiate RX amplifier (differential pair)
- [ ] Add transmission line model for channel
- [ ] Add bias and supply networks

### Phase 3: Testing
- [ ] DC operating point analysis (.OP)
- [ ] Transient analysis with data pattern
- [ ] Verify signal integrity across channel
- [ ] Extract behavioral models via SynapticAMS pipeline

### Phase 4: Behavioral Model Generation
- [ ] Run VCO through pipeline → oscillator model
- [ ] Run TX driver through pipeline → DC sweep model
- [ ] Run RX amplifier through pipeline → DC sweep model
- [ ] Generate hierarchical Verilog-AMS for complete SERDES

---

## Test Scenarios

### Test 1: DC Operating Point
- Verify all bias points within valid ranges
- Check supply currents
- Confirm differential pair operating in linear region

### Test 2: Single-Tone Transmission
- VCO generates 589 MHz clock
- TX driver outputs differential sine wave
- RX amplifier recovers signal
- Measure: amplitude, phase shift, distortion

### Test 3: Data Pattern Transmission (Future)
- TX sends PRBS pattern
- RX recovers pattern
- Measure: eye diagram, BER

---

## Success Criteria

For SynapticAMS pipeline validation:

1. ✅ **Block-Level Validation**
   - VCO: Oscillation at expected frequency (✅ 589 MHz)
   - Differential Pair: S-curve transfer characteristic (✅ 25V swing)

2. **System-Level Integration** (IN PROGRESS)
   - All blocks instantiate without errors
   - DC operating point converges
   - Transient simulation runs to completion

3. **Behavioral Model Generation** (PENDING)
   - VCO → Verilog-AMS oscillator model
   - TX/RX → Verilog-AMS lookup table models
   - Complete hierarchy simulates in Verilog-AMS simulator

4. **Accuracy Validation** (PENDING)
   - NRMSE < 5% between SPICE and behavioral models
   - Waveform comparison shows good agreement

---

## File Organization

```
~/SynapticAMS/
├── SERDES_BLOCK_INVENTORY.md       # Block discovery and status
├── SERDES_VALIDATION_PLAN.md       # Overall validation plan
├── MINIMAL_SERDES_DESIGN.md        # This file
├── blocks/                          # Individual block netlists
│   ├── vco_sub.cir                 # VCO subcircuit
│   ├── diffpair.cir                # Differential pair
│   └── models/                      # Transistor models (BSIM3, Gummel-Poon)
├── serdes_top.cir                  # Top-level SERDES netlist (TO CREATE)
├── test_vco_analysis.py            # VCO test script (✅)
├── test_diffpair_simple.py         # Diffpair test script (✅)
└── test_serdes_complete.py         # Full SERDES test (TO CREATE)
```

---

## Next Steps

1. Create `serdes_top.cir` with integrated VCO + TX + RX
2. Add simple transmission line channel model
3. Run transient simulation with test pattern
4. Generate behavioral models for each block
5. Create hierarchical Verilog-AMS netlist
6. Validate behavioral model accuracy

---

**Status:** Phase 3 - SERDES IP Design - IN PROGRESS
**Completion:** 40% (2/5 blocks validated, integration pending)
