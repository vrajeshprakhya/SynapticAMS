# Where to Find SPICE/EC Results - Quick Reference

## 📊 After Running Validated Demo

```bash
python3 demo_warmstart_validated.py examples/netlists/serdes_cml.cir -o ./results 2>&1 | tee demo.log
```

## 🎯 Result Locations

### 1. **Detailed Metrics Report** ⭐ (RECOMMENDED)

```bash
cat ./results/validation_report.txt
```

**Sample Output:**
```
Module: rx_out_p_vs_tx_in_p_rx_tail
  Pass 1 (AI refinement): success
  Pass 2 (Validation): passed
  Pass 3 (Error correction): not_needed
  Final version: pass1

  SPICE/EC Validation Metrics:
    Max Absolute Error: 1.234567e-04
    Max Relative Error: 2.34%
    RMS Error:          5.678901e-05
    Correlation:        0.998765
    Coverage:           100.0%
```

### 2. **JSON Metrics** (Programmatic Access)

```bash
cat ./results/validation_metrics.json
```

**Sample Output:**
```json
[
  {
    "module": "rx_out_p_vs_tx_in_p_rx_tail",
    "pass1": "success",
    "validation": "passed",
    "pass3": "not_needed",
    "final": "pass1",
    "metrics": {
      "max_abs_error": 0.00012345,
      "max_rel_error": 0.0234,
      "rms_error": 0.00005679,
      "correlation": 0.998765,
      "coverage": 100.0
    },
    "error_msg": null
  }
]
```

**Parse with jq:**
```bash
# Extract all max_abs_error values
jq '.[] | {module: .module, error: .metrics.max_abs_error}' ./results/validation_metrics.json

# Find modules that passed validation
jq '.[] | select(.validation == "passed") | .module' ./results/validation_metrics.json

# Get correlation scores
jq '.[] | {module: .module, correlation: .metrics.correlation}' ./results/validation_metrics.json
```

### 3. **Console Output** (Real-time)

```bash
# Extract equivalence check results
grep "Pass 2" demo.log

# Example output:
#   Pass 2: Equivalence check... ✓ PASS (err=1.23e-04, corr=0.998)
#   Pass 2: Equivalence check... ⚠ FAIL - Compilation error: syntax error
```

### 4. **OSDI Testbenches** (Debug)

```bash
ls ./results/testbenches/block_0/
```

**Files:**
- `*_spice.cir` - SPICE testbench with test vectors
- `*_vams.cir` - OSDI testbench (compiled Verilog-AMS)
- `test_manifest.json` - Test vector coordinates

**Example:**
```bash
# View SPICE testbench for a specific module
cat ./results/testbenches/block_0/rx_out_p_vs_tx_in_p_rx_tail_spice_0.cir
```

## 📈 Interpreting Metrics

### Max Absolute Error
- **What**: Largest |SPICE - OSDI| across all test points
- **Good**: < 1e-3 (1mV for voltages)
- **Acceptable**: < 1e-2
- **Bad**: > 1e-1

### Max Relative Error
- **What**: Largest |(SPICE - OSDI)/SPICE|
- **Good**: < 5%
- **Acceptable**: < 10%
- **Bad**: > 20%

### RMS Error
- **What**: Root mean square error across all test points
- **Good**: < 1e-4
- **Indicates**: Overall fit quality

### Correlation
- **What**: Pearson correlation coefficient
- **Good**: > 0.98 (strong correlation)
- **Acceptable**: > 0.95
- **Bad**: < 0.90

### Coverage
- **What**: % of test points that converged
- **Good**: 100%
- **Warning**: < 95% indicates convergence issues

## 🔍 Common Queries

### Which modules passed validation?
```bash
grep "Pass 2.*PASS" demo.log
# or
jq '.[] | select(.validation == "passed") | .module' ./results/validation_metrics.json
```

### Which modules needed error correction?
```bash
jq '.[] | select(.pass3 == "success") | .module' ./results/validation_metrics.json
```

### Which modules fell back to baseline?
```bash
jq '.[] | select(.final == "baseline_fallback")' ./results/validation_metrics.json
```

### What was the average max_error?
```bash
jq '[.[] | .metrics.max_abs_error] | add / length' ./results/validation_metrics.json
```

### Show all modules with correlation < 0.98
```bash
jq '.[] | select(.metrics.correlation < 0.98) | {module: .module, corr: .metrics.correlation}' ./results/validation_metrics.json
```

## 📂 Complete File Structure

```
./results/
├── validation_report.txt          ⭐ Human-readable metrics
├── validation_metrics.json        ⭐ Machine-readable metrics
├── refined/                        # Final validated models
│   ├── rx_out_p_vs_tx_in_p_rx_tail.va
│   └── ...
├── nonai/                          # Baseline models
│   └── ...
├── testbenches/                    # Debug SPICE/OSDI netlists
│   └── block_0/
│       ├── rx_out_p_vs_tx_in_p_rx_tail_spice_0.cir
│       ├── rx_out_p_vs_tx_in_p_rx_tail_vams_0.cir
│       └── test_manifest.json
├── comparison_all_modules.txt      # Code diff (baseline vs refined)
└── WARMSTART_SUMMARY.txt           # Overall summary
```

## 🚀 Quick Analysis Commands

### Summary Statistics
```bash
echo "=== Validation Summary ==="
echo "Total modules: $(jq 'length' ./results/validation_metrics.json)"
echo "Passed validation: $(jq '[.[] | select(.validation == "passed")] | length' ./results/validation_metrics.json)"
echo "Needed correction: $(jq '[.[] | select(.pass3 == "success")] | length' ./results/validation_metrics.json)"
echo "Baseline fallback: $(jq '[.[] | select(.final == "baseline_fallback")] | length' ./results/validation_metrics.json)"
```

### Best/Worst Models
```bash
echo "=== Best Model (lowest error) ==="
jq 'min_by(.metrics.max_abs_error) | {module: .module, error: .metrics.max_abs_error}' ./results/validation_metrics.json

echo "=== Worst Model (highest error) ==="
jq 'max_by(.metrics.max_abs_error) | {module: .module, error: .metrics.max_abs_error}' ./results/validation_metrics.json
```

### Correlation Report
```bash
echo "=== Correlation Report ==="
jq -r '.[] | "\(.module): \(.metrics.correlation)"' ./results/validation_metrics.json | column -t
```

## 💡 Tips

1. **Always save console output** with `tee`:
   ```bash
   python3 demo_warmstart_validated.py netlist.cir 2>&1 | tee demo.log
   ```

2. **Check JSON first** for programmatic analysis:
   ```bash
   cat validation_metrics.json | jq .
   ```

3. **Use validation_report.txt** for human review:
   ```bash
   less validation_report.txt
   ```

4. **Debug failing modules** by checking testbenches:
   ```bash
   cd testbenches/block_0
   ngspice -b failing_module_spice_0.cir
   ```

## 📞 Support

If you see unexpected results:
1. Check `validation_report.txt` for error messages
2. Review `validation_metrics.json` for detailed numbers
3. Inspect testbenches in `testbenches/` directory
4. Compare with baseline metrics from Step 1 (non-AI pipeline)
