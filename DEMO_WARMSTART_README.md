# SynapticAMS Warm-Start Demo

Single-command demo showing **SPICE → Verilog-AMS conversion** using the **Warm-Start method**.

## What is Warm-Start?

The Warm-Start method combines the strengths of both approaches:
1. **Non-AI pipeline** generates numerically-fitted baseline (high precision)
2. **AI agent** refines the baseline with domain knowledge (intelligent modeling)

### Test Results

Based on comprehensive testing across 4 netlists:

```
Method              nmos_dc_sweep    SerDes_cml      Best For
──────────────────────────────────────────────────────────────────────
Pure AI             1.3171 NRMSE    N/A (dynamic)   Novel circuits
Pure Non-AI         2.2532 NRMSE    1.2999 NRMSE    Reliable baseline
Warm-Start          0.8123 NRMSE    N/A (dynamic)   ✓ Simple DC amplifiers
AI Judge            FAILED           0.0528 NRMSE    ✓ Complex RF/SerDes
```

**Warm-Start wins on simple amplifiers** (38% better than pure AI, 64% better than Non-AI)

## Quick Start

### Run the Demo

```bash
python3 demo_warmstart.py examples/netlists/serdes_cml.cir
```

### Output

The demo generates:
```
/tmp/synapticams_warmstart_demo_serdes_cml/
├── baseline.va           # Non-AI numeric model
├── refined.va            # AI-refined warm-start model
├── comparison.txt        # Side-by-side comparison
├── WARMSTART_SUMMARY.txt # Full summary
└── nonai/                # All generated modules (18 files)
```

### Review Results

```bash
# View the refined model
cat /tmp/synapticams_warmstart_demo_serdes_cml/refined.va

# See what changed
cat /tmp/synapticams_warmstart_demo_serdes_cml/comparison.txt

# Read full summary
cat /tmp/synapticams_warmstart_demo_serdes_cml/WARMSTART_SUMMARY.txt
```

## How It Works

### Step 1: Non-AI Baseline Generation
- Analyzes circuit structure
- Runs ngspice DC sweeps (1D or 2D)
- Fits transfer functions numerically
- Generates Verilog-AMS modules

For SerDes example:
- Found **19 devices**, **1 functional block**
- Detected **coupled inputs** → generated **2D lookup table**
- Created **9 Verilog-AMS modules** (5 coupled_nonlinear + 4 small-signal)

### Step 2: AI Refinement
- Sends netlist + baseline model to AI agent (llama3.2:3b)
- AI refines transfer functions and adds domain knowledge
- Maintains baseline structure for stability

For SerDes example:
- Baseline: 1102 chars, 35 lines, 7 parameters
- Refined: 1133 chars, 40 lines, 5 parameters

### Step 3: Comparison
- Shows side-by-side differences
- Highlights parameter changes
- Documents model evolution

## Requirements

All requirements are automatically checked:

```
✓ ngspice          - Circuit simulation
✓ OpenVAF          - Verilog-AMS compiler
✓ Ollama           - AI backend (llama3.2:3b)
✓ pipeline_ext     - Non-AI numeric pipeline
✓ ai_agent         - AI interface
```

## When to Use Warm-Start

### ✅ Good For:
- Simple amplifiers and DC circuits
- When pure AI struggles to converge
- When you need numeric precision + AI intelligence
- Circuits with clear DC transfer characteristics

### ❌ Not Good For:
- Complex RF/SerDes circuits (use **AI Judge** instead)
- Circuits where non-AI baseline is very poor
- Highly dynamic systems with oscillations

## Other Pipeline Methods

| Method | Best For | Test Results |
|--------|----------|--------------|
| **Pure AI** | Novel circuits, creative modeling | 1.3171 NRMSE (nmos_dc_sweep) |
| **Pure Non-AI** | Reliable baseline, fallback | 2.2532 NRMSE (nmos_dc_sweep) |
| **Warm-Start** | Simple DC amplifiers | 0.8123 NRMSE (38% better than AI) |
| **AI Judge** | Complex SerDes/RF | 0.0528 NRMSE (serdes_cml) |

## Example Run

```bash
$ python3 demo_warmstart.py examples/netlists/serdes_cml.cir

================================================================================
                          SynapticAMS Warm-Start Demo
================================================================================

ℹ  SPICE → Verilog-AMS conversion using Non-AI baseline + AI refinement
ℹ  Input: examples/netlists/serdes_cml.cir
ℹ  Output: /tmp/synapticams_warmstart_demo_serdes_cml

[Step 0/4] Checking capabilities...
✓  ngspice found
✓  Ollama LLM backend available
✓  OpenVAF compiler found
✓  Non-AI pipeline available (pipeline_ext)
✓  AI agent available
✓  All required tools available

[Step 1/4] Running Non-AI baseline generation (numeric fitting)...
...
✓  Selected baseline: rx_out_p_vs_tx_tail_tx_in_n
✓  Saved to: /tmp/synapticams_warmstart_demo_serdes_cml/baseline.va

Non-AI Baseline Summary:
  • Total modules generated: 9
  • Selected baseline: rx_out_p_vs_tx_tail_tx_in_n
  • Baseline size: 1102 chars
  • Method: Numeric transfer function fitting

[Step 2/4] Running AI refinement (warm-start)...
✓  Saved to: /tmp/synapticams_warmstart_demo_serdes_cml/refined.va

AI Refinement Summary:
  • Model size: 1133 chars (baseline: 1102 chars)
  • Method: LLM-based refinement with domain knowledge

[Step 3/4] Comparing baseline vs refined models...
✓  Comparison saved to: comparison.txt

Key Differences:
  • Baseline lines: 35
  • Refined lines: 40
  • Size change: +31 chars
  • Parameters: 7 → 5

[Step 4/4] Generating summary...
✓  Summary saved to: WARMSTART_SUMMARY.txt

================================================================================
Demo Complete!
================================================================================
```

## Next Steps

1. **Review generated models**:
   ```bash
   cat /tmp/synapticams_warmstart_demo_serdes_cml/refined.va
   ```

2. **Compile with OpenVAF**:
   ```bash
   cd /tmp/synapticams_warmstart_demo_serdes_cml
   openvaf refined.va -o refined.osdi
   ```

3. **Test in ngspice** (requires testbench):
   ```bash
   ngspice -b testbench.sp
   ```

4. **Try other netlists**:
   ```bash
   python3 demo_warmstart.py examples/netlists/nmos_dc_sweep.cir
   python3 demo_warmstart.py examples/netlists/bjt_amplifier.cir
   ```

## Known Issues

1. **AI-generated code may have syntax errors**
   - AI sometimes uses undefined variables
   - Solution: Use Test 4 (OSDI validation) to verify

2. **Warm-Start doesn't work for dynamic models**
   - Models with `laplace_nd`, `ddt`, `idt` need OSDI validation
   - Solution: Use AI Judge method for dynamic circuits

3. **Test 4 (OSDI) currently fails on all netlists**
   - Need to fix VA code generation bugs
   - See: `IMPLEMENTATION_SUMMARY.md` for details

## Architecture Recommendation

Based on test results, the recommended validation approach is:

**Move from Python NRMSE → OSDI-only validation**

Current (has false positives):
- Tests 1-3 use Python evaluator → unreliable
- Test 4 uses OSDI → ground truth (but currently broken)

Proposed (all tests use ground truth):
- All tests use OpenVAF + OSDI ngspice validation
- Python evaluator removed or demoted to "quick sanity check"
- Forces code quality and real simulation results

## Files

- `demo_warmstart.py` - Main demo script (390 lines)
- `examples/netlists/serdes_cml.cir` - Example SerDes netlist
- `DEMO_WARMSTART_README.md` - This file

## Related Documentation

- `IMPLEMENTATION_SUMMARY.md` - Full pipeline test results
- `PIPELINE_FALLBACK_GUIDE.md` - How pipeline chooses methods
- `tests/test_pipeline_comparison.py` - Full test suite (994 lines)
