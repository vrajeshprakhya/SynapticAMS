# SERDES Analog Block Inventory

## Discovery Status: Complete
**Last Updated:** 2026-03-10

---

## Block Status Legend:
- ✅ **FOUND** - Circuit file located and validated
- ⚠️ **PARTIAL** - Related circuit found, may need adaptation
- ❌ **MISSING** - Not found in current repositories
- 🔨 **CUSTOM** - Need to design from scratch

---

## Priority 1: Core SERDES Analog Blocks

### 1. VCO (Voltage-Controlled Oscillator)
**Status:** ✅ FOUND
**Location:** `~/eda_tools/ngspice/examples/xspice/pll/vco_sub.cir`
**Type:** 7-stage differential ring oscillator (BSIM3)
**Frequency Range:** 150-900 MHz
**Test Status:** ✅ TESTED (589 MHz achieved)
**Pipeline Status:** ✅ VALIDATED
**Notes:** Fully functional, behavioral model generated

---

### 2. Phase Detector (PD)
**Status:** ✅ FOUND
**Location:** `~/eda_tools/ngspice/examples/xspice/pll/f-p-det-d-sub.cir`
**Type:** Phase-Frequency Detector (Digital)
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED
**Notes:** Part of complete PLL example

---

### 3. Loop Filter (Charge Pump + RC Filter)
**Status:** ✅ FOUND
**Locations:**
- `~/eda_tools/ngspice/examples/xspice/pll/loop-filter.cir` (2nd order)
- `~/eda_tools/ngspice/examples/xspice/pll/loop-filter-2.cir` (2nd/3rd order with transistor switches)

**Type:** Switched current source charge pump + passive RC filter
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED
**Components:**
- Current sources: 5mA switched
- R=200Ω, C1=5nF, C2=5nF

---

### 4. CML/ECL Driver (Differential Output Driver)
**Status:** ✅ FOUND
**Locations:**
- `~/eda_tools/ngspice/examples/osdi/hicuml0/ECL-OR.cir` (ECL OR gate)
- `~/eda_tools/ngspice/examples/cider/parallel/eclinv.cir` (ECL inverter)

**Type:** Current-steering differential pairs (BJT-based ECL)
**Supply:** VEE = -5.2V, VCC = 0V
**Logic Levels:** -0.9V to -1.75V (~850mV swing)
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED
**Notes:** Need to adapt to CMOS CML for modern processes

---

### 5. Differential Amplifier/Buffer
**Status:** ✅ FOUND
**Location:** `~/eda_tools/ngspice/examples/tclspice/tcl/diffpair.cir`
**Type:** BJT differential pair with current mirror bias
**Supply:** ±12V
**Test Status:** ✅ TESTED
**Pipeline Status:** ✅ VALIDATED
**Performance:**
- Differential output swing: 25.24V
- S-curve transfer characteristic confirmed
- Common-mode output: 5.72V ± 0.22V
**Components:**
- Differential pair: Q1, Q2 (NPN BJTs)
- Current mirror bias: Q3, Q4
- Collector resistors: 10kΩ

---

### 6. High-Speed Comparator
**Status:** ⚠️ PARTIAL
**Location:** `~/eda_tools/ngspice/examples/xspice/see/CMOSComparator/Fig27_12_see.sp`
**Type:** CMOS comparator
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED
**Notes:** Need to verify suitability for high-speed operation

**Alternative Location:** `~/eda_tools/ngspice/examples/p-to-n-examples/relax_osc_st.cir` (relaxation oscillator with schmitt trigger behavior)

---

### 7. Current Mirror
**Status:** ⚠️ PARTIAL
**Location:** Found implicitly in differential pair circuits
**Type:** Can extract from existing designs
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED
**Notes:**
- Present in diffpair.cir (Q3, Q4 form current mirror)
- Can create standalone testbench

---

### 8. Reference Voltage Generator
**Status:** ⚠️ PARTIAL
**Location:** Reference voltages in PLL examples (resistor dividers)
**Type:** Simple resistor divider (not true bandgap)
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED
**Notes:**
- PLL uses resistor-based reference (R3, R4 in vco_sub.cir)
- No true bandgap reference found
- May need to design simple bandgap or use resistor divider

---

## Priority 2: Advanced SERDES Features

### 9. CTLE (Continuous-Time Linear Equalizer)
**Status:** ❌ MISSING
**Location:** Not found in surveyed repositories
**Alternative:** Can design as RC high-pass filter or active inductor
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED

---

### 10. Pre-Emphasis Driver (FIR Filter)
**Status:** ❌ MISSING
**Location:** Not found
**Alternative:** Can design as programmable current source array
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED

---

### 11. AGC (Automatic Gain Control)
**Status:** ❌ MISSING
**Location:** Not found
**Alternative:** May use fixed-gain amplifier for simplicity
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED

---

### 12. Offset Cancellation Circuit
**Status:** ❌ MISSING
**Location:** Not found
**Alternative:** May skip for initial demo
**Test Status:** ⏳ PENDING
**Pipeline Status:** ⏳ NOT TESTED

---

## Summary Statistics

### Block Availability:
- **Found (✅):** 5 blocks (VCO, PD, Loop Filter, ECL Driver, Diff Pair)
- **Partial (⚠️):** 3 blocks (Comparator, Current Mirror, Vref)
- **Missing (❌):** 4 blocks (CTLE, Pre-emphasis, AGC, Offset Cancel)

### Testing Progress:
- **Tested (✅):** 2 blocks (VCO, Differential Pair)
- **Pending (⏳):** 10 blocks
- **Completion:** 17% (2/12)

### Pipeline Validation:
- **Validated (✅):** 2 blocks (VCO, Differential Pair)
- **Not Tested (⏳):** 10 blocks
- **Completion:** 17% (2/12)

---

## Minimal SERDES Configuration (MVP)

For initial demonstration, we can build a minimal SERDES using only **found blocks**:

### TX Path:
1. ✅ **PLL** (VCO + PD + Loop Filter) - Clock multiplication
2. ✅ **CML Driver** (ECL output stage) - Differential output

### RX Path:
3. ✅ **Differential Buffer** (Diff pair) - Input amplification
4. ⚠️ **Comparator** - Data sampling
5. ✅ **CDR** (Re-use PLL architecture) - Clock recovery

### Common:
6. ⚠️ **Current Mirror** - Bias generation
7. ⚠️ **Voltage Reference** - Reference generation

**Minimum Viable Blocks:** 7
**Availability:** 5 fully available, 2 partially available
**Feasibility:** ✅ **HIGH** - Can build complete SERDES from found blocks

---

## Next Actions

### Immediate (Phase 1):
1. ✅ Complete amsnet_1.0 survey (no useful blocks found)
2. ⏳ Validate partial blocks (comparator, current mirror)
3. ✅ Update inventory with findings

### Short-term (Phase 2):
1. ⏳ Test Phase Detector through pipeline
2. ⏳ Test Loop Filter through pipeline
3. ⏳ Test ECL Driver through pipeline
4. ⏳ Test Differential Pair through pipeline
5. ⏳ Test Comparator through pipeline

### Medium-term (Phase 3):
1. 🔨 Design simple current mirror testbench
2. 🔨 Design voltage reference (resistor divider)
3. 🔨 Optionally design CTLE (RC high-pass)
4. 🔨 Assemble minimal SERDES IP

---

## Repository Survey Status

### ~/eda_tools/ngspice/examples
**Status:** ✅ SURVEYED
**Key Findings:**
- Complete PLL (VCO, PD, Loop Filter)
- ECL logic gates (current mode logic)
- Differential pairs and amplifiers
- Some comparator examples

### /mnt/c/Users/vraje/Downloads/amsnet_1.0
**Status:** ✅ SURVEYED
**Structure:** 734 numbered directories with individual circuits
**Format:** Simple SPICE netlists (.cir files)
**Circuit Complexity:** 1-19 transistors per circuit
**Findings:** Synthetic test circuits only - NO functional analog blocks
**Conclusion:** NOT useful for SERDES IP (appears to be ML training dataset)

### Additional Sources
**Status:** ⏳ NOT SURVEYED
**Candidates:**
- Sky130 PDK examples
- OpenRAM analog blocks
- Academic/research repositories

---

**Created:** 2026-03-10
**Last Updated:** 2026-03-10
**Status:** Phase 2 - Block Testing 17% Complete, Phase 3 - SERDES IP Design Starting
