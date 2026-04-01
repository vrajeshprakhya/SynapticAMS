# Validated Warm-Start Demo

## Overview

Enhanced warm-start demo with **3-pass AI refinement and validation feedback loop**:

```
┌─────────────────────────────────────────────────────────────┐
│ Pass 1: AI Refinement                                       │
│   ↓ AI improves baseline model                             │
├─────────────────────────────────────────────────────────────┤
│ Pass 2: OSDI + Equivalence Check                           │
│   ↓ Compile with OpenVAF + validate with ngspice           │
│   ↓ Collect: errors, metrics, failure reasons              │
├─────────────────────────────────────────────────────────────┤
│ Pass 3: AI Error Correction (if validation fails)          │
│   ↓ Feed validation errors back to AI                      │
│   ↓ AI fixes syntax/accuracy/timeout issues                │
│   ↓ Re-validate corrected model                            │
├─────────────────────────────────────────────────────────────┤
│ Final: Best validated model (Pass 1, Pass 3, or Baseline)  │
└─────────────────────────────────────────────────────────────┘
```

## Key Improvements

### vs. Basic `demo_warmstart.py`:

| Feature | Basic Demo | Validated Demo |
|---------|------------|----------------|
| AI refinement | ✓ Single pass | ✓ 3-pass with feedback |
| Validation | ✗ Baseline only | ✓ Every refined module |
| Error correction | ✗ None | ✓ AI fixes mistakes |
| Quality guarantee | ✗ Trust AI blindly | ✓ Validated or fallback |
| Compilation check | ✗ Manual | ✓ Automatic per module |
| Equivalence check | ✗ Baseline only | ✓ Per refinement pass |

## Usage

```bash
# Basic usage (same as original demo)
python3 demo_warmstart_validated.py examples/netlists/serdes_cml.cir

# With custom output directory
python3 demo_warmstart_validated.py examples/netlists/serdes_cml.cir -o ./validated_results

# With logging
python3 demo_warmstart_validated.py examples/netlists/serdes_cml.cir 2>&1 | tee validated_demo.log
```

## Output Structure

```
output_directory/
├── baseline_example.va                 # Example non-AI model
├── nonai/                               # All non-AI baseline modules
├── refined/                             # AI-refined AND validated modules ⭐
│   ├── rx_out_p_vs_tx_in_p_rx_tail.va  # Final validated version
│   └── ...
├── testbenches/                         # OSDI testbenches for validation
│   ├── block_0/
│   └── ...
├── validation_report.txt                # Detailed validation report ⭐
├── comparison_all_modules.txt           # Side-by-side comparison
└── WARMSTART_SUMMARY.txt                # Summary
```

## 3-Pass Workflow Example

### Successful Pass 1 Validation

```
[1/5] rx_out_p_vs_tx_in_p_rx_tail
  Pass 1: AI refinement... ✓ (+2472 chars)
  Pass 2: Equivalence check... ✓ PASS (err=1.23e-04, corr=0.998)
  Final: Using Pass 1 (validated)
```

### Failed Pass 1, Successful Pass 3 Correction

```
[2/5] tx_out_n_vs_tx_in_p_rx_tail
  Pass 1: AI refinement... ✓ (+1303 chars)
  Pass 2: Equivalence check... ⚠ FAIL - Compilation error: syntax error at line 23
  Pass 3: AI error correction... ✓ FIXED (err=3.45e-04)
  Final: Using Pass 3 (corrected)
```

### Failed Both Passes, Fallback to Baseline

```
[3/5] rx_out_n_vs_tx_in_p_rx_tail
  Pass 1: AI refinement... ✓ (-20 chars)
  Pass 2: Equivalence check... ⚠ FAIL (err=5.67e-02, corr=0.234)
  Pass 3: AI error correction... ✗ Still failing, using baseline
  Final: Using Baseline (fallback)
```

## Validation Report

The `validation_report.txt` provides per-module details:

```
================================================================================
AI Refinement Validation Report
================================================================================

Module: rx_out_p_vs_tx_in_p_rx_tail
  Pass 1 (AI refinement): success
  Pass 2 (Validation): passed
  Pass 3 (Error correction): not_needed
  Final version: pass1

Module: tx_out_n_vs_tx_in_p_rx_tail
  Pass 1 (AI refinement): failed
  Pass 2 (Validation): failed
  Pass 3 (Error correction): success
  Final version: pass3_corrected

Module: rx_out_n_vs_tx_in_p_rx_tail
  Pass 1 (AI refinement): failed
  Pass 2 (Validation): failed
  Pass 3 (Error correction): failed
  Final version: baseline_fallback
```

## Summary Statistics

At the end, you'll see:

```
AI Refinement with Validation Summary:
  • Modules refined: 5
  • Pass 1 (AI refinement): 3/5 succeeded
  • Pass 2 (Validation): 3/5 passed
  • Pass 3 (Error correction): 1 fixed
  • Baseline fallback: 1
  • Output directory: validated_results/refined
```

## Error Types Handled

### 1. Compilation Errors (OpenVAF)
- **Cause**: Syntax errors, semantic errors, unsupported constructs
- **Detection**: OpenVAF compilation failure
- **Correction**: AI fixes syntax based on error message

### 2. Accuracy Errors (Equivalence Check)
- **Cause**: Poor transfer function fit, wrong equations
- **Detection**: High max_error, low correlation
- **Correction**: AI improves behavioral equations

### 3. Timeout Errors (Simulation)
- **Cause**: Overly complex dynamics, numerical instability
- **Detection**: ngspice simulation timeout
- **Correction**: AI simplifies model (remove complex terms)

## When to Use This Demo

✅ **Use validated demo when:**
- You need guaranteed model quality
- You want AI to learn from mistakes
- You're deploying models to production
- You need validation reports for auditing

❌ **Use basic demo when:**
- Quick prototyping/exploration
- You'll manually validate anyway
- Speed is more important than validation

## Performance Considerations

**Time comparison for 5 modules:**
- Basic demo: ~2 minutes (AI refinement only)
- Validated demo: ~8-12 minutes (3 passes + validation)

**Why slower?**
- 2-3x AI calls per module (Pass 1 + optional Pass 3)
- OSDI compilation per module (OpenVAF)
- Equivalence checking per module (ngspice)

**Optimization tips:**
- Use faster AI model (e.g., `llama3.2:3b` vs `llama3.2:70b`)
- Reduce equivalence check grid density
- Parallelize validation (future improvement)

## Troubleshooting

### "All modules fell back to baseline"
- Check if AI backend is working: `curl http://192.168.1.34:11434/api/tags`
- Try with Anthropic: set `ANTHROPIC_API_KEY` environment variable
- Reduce model complexity (AI might be hallucinating)

### "Equivalence checking times out"
- Increase timeout in `validate_module()` function
- Reduce DC sweep grid size in `equivalence_checker.py`
- Use point-by-point fallback (automatic)

### "OpenVAF compilation fails for all modules"
- Check OpenVAF version: `openvaf --version`
- Verify baseline models compile first
- Review error messages in validation report

## Integration with Existing Workflow

This demo can replace the basic `demo_warmstart.py` in your workflow:

```bash
# Before
python3 demo_warmstart.py netlist.cir
# Manual validation...

# After
python3 demo_warmstart_validated.py netlist.cir
# Automatic validation + error correction!
```

## Future Enhancements

Potential improvements:
- [ ] Parallel validation of independent modules
- [ ] More sophisticated error classification
- [ ] Multi-round correction (up to N attempts)
- [ ] Differential validation (baseline vs refined)
- [ ] Confidence scoring based on validation metrics
- [ ] A/B testing: AI vs baseline side-by-side

## Support

For issues or questions:
- Check `validation_report.txt` for detailed failure reasons
- Review equivalence checker logs in `testbenches/`
- Compare with basic demo results
- File an issue with validation report attached
