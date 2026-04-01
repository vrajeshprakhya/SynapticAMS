# 2D OSDI Equivalence Checking Issue

## Problem Summary

OSDI equivalence checking is now enabled (import bug fixed), but **all 5 checks are failing** with:
```
Warning: 2D DC sweep failed: All retry strategies failed
Last error: No data points in 2D simulation output
```

## Root Cause

The equivalence checker at `equivalence_checker/equivalence_checker.py` attempts to validate 2D lookup table models by running a 2D DC sweep. However, the current implementation has issues:

### Issue 1: Variable Name Mismatch
**Location**: `ngspice_runner.py:383-468` (`_parse_dc_sweep_2d_output`)

The parser tries to match ngspice output columns to requested variable names:
```python
for var in all_vars:
    if norm_col == var.lower() or col_lo == var.lower():
        all_data[var].append(values[i])
```

**Problem**: The Verilog-AMS model ports (e.g., `tx_in_n`, `rx_tail`) may not match the instantiated node names in the equivalence testbench.

### Issue 2: 2D Testbench Generation
**Location**: Need to check `equivalence_checker.py` for 2D validation logic

The equivalence checker needs to:
1. Extract the two input variables from the 2D LUT model
2. Generate a testbench that sweeps both inputs
3. Instantiate the OSDI model correctly with matching port names

## Why 5 Checks?

**Answer**: The logic is:
- **Total modules**: 9 (5 coupled_nonlinear + 4 small-signal)
- **OSDI checks**: 5 (only on coupled_nonlinear 2D LUT models)
- **Small-signal skipped**: 4 (parameter validation only, no simulation needed)

The 5 coupled_nonlinear modules are:
1. `rx_out_n_vs_tx_in_n_rx_tail` (2D: tx_in_n × rx_tail → rx_out_n)
2. `tx_tail_vs_tx_in_n_rx_tail` (2D: tx_in_n × rx_tail → tx_tail)
3. `tx_out_n_vs_tx_in_n_rx_tail` (2D: tx_in_n × rx_tail → tx_out_n)
4. `rx_out_p_vs_tx_in_n_rx_tail` (2D: tx_in_n × rx_tail → rx_out_p)
5. `tx_out_p_vs_tx_in_n_rx_tail` (2D: tx_in_n × rx_tail → tx_out_p)

## Debug Steps

### Step 1: Check what the equivalence checker is passing

Need to add debug logging to see:
```python
# In equivalence_checker.py, when calling 2D sweep
print(f"DEBUG: sweep_var_1 = {sweep_var_1}")
print(f"DEBUG: sweep_var_2 = {sweep_var_2}")
print(f"DEBUG: observe_vars = {observe_vars}")
```

### Step 2: Check actual ngspice output

The parser expects output like:
```
Index   tx_in_n   rx_tail   rx_out_n
---------------------------------------
0       0.0       0.0       0.123
1       0.0       0.1       0.234
...
```

But might be getting something different. Need to capture and inspect actual output.

### Step 3: Check Verilog-AMS port names

Look at one of the generated `.va` files to confirm port names:
```bash
cat /tmp/synapticams_warmstart_demo_serdes_cml/nonai/rx_out_n_vs_tx_in_n_rx_tail.va
```

## Recommended Fix

### Option 1: Skip 2D OSDI Validation for Now (Quick Fix)

Modify `equivalence_checker.py` or `complete_pipeline.py` to skip OSDI checks for 2D models:

```python
# In complete_pipeline.py around line 780
if '2D' in module_name or 'coupled' in str(block_info.get('behavior_class', '')):
    print(f"      ○ {module_name}: 2D model (OSDI validation not yet supported)")
    continue
```

### Option 2: Fix 2D Testbench Generation (Proper Fix)

1. **Extract input/output names from module**:
   ```python
   # Parse .va file to get module ports
   import re
   match = re.search(r'module\s+(\w+)\s*\((.*?)\)', va_code, re.DOTALL)
   ports = [p.strip().split()[-1] for p in match.group(2).split(',')]
   inputs = ports[:-1]  # All but last
   output = ports[-1]   # Last port
   ```

2. **Generate proper 2D testbench**:
   ```verilog
   * 2D Equivalence Testbench
   V1 tx_in_n 0 DC 0
   V2 rx_tail 0 DC 0

   .control
   pre_osdi model.osdi
   .endc

   .model mymodel rx_out_n_vs_tx_in_n_rx_tail
   Nmodel tx_in_n rx_tail rx_out_n mymodel

   .dc V1 0 1.8 0.3 V2 0 1.8 0.3
   .print dc v(tx_in_n) v(rx_tail) v(rx_out_n)
   .end
   ```

3. **Update parser to handle OSDI node naming**:
   ```python
   # OSDI models may use different node names
   # Need to map Verilog-A port names to testbench node names
   ```

## Current Status

- ✅ OSDI equivalence checking is now **enabled** (import bug fixed)
- ⚠️ All 5 checks **fail** due to 2D testbench issue
- ✅ Small-signal models (4) correctly skip OSDI (use parameter validation)
- 📋 Need to implement proper 2D OSDI validation logic

## Next Steps

1. Add debug logging to capture actual ngspice output
2. Inspect one of the generated `.va` files to understand port structure
3. Decide: Quick fix (skip 2D) or proper fix (implement 2D validation)
