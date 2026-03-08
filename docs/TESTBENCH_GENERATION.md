# Testbench Generation in Equivalence Checker

## Overview

The equivalence checker now **formalizes** testbench generation by saving testbenches to organized directories during pipeline execution. This provides transparency, reproducibility, and debugging capabilities.

## Directory Structure

When testbench saving is enabled, the following structure is created:

```
testbench_output_dir/
├── block_name_1/
│   ├── spice/
│   │   ├── testbench_000.cir
│   │   ├── testbench_050.cir
│   │   ├── testbench_100.cir
│   │   └── ...
│   ├── verilog_ams/
│   │   ├── testbench_000.cir
│   │   ├── testbench_050.cir
│   │   ├── testbench_100.cir
│   │   └── ...
│   └── test_manifest.json
├── block_name_2/
│   ├── spice/
│   ├── verilog_ams/
│   └── test_manifest.json
└── ...
```

## What Gets Saved

### Representative Subset

To avoid file explosion (hundreds of testbenches per block), only **representative samples** are saved:

- If total vectors **≤ 20**: Save all testbenches
- If total vectors **> 20**: Save 15 representative testbenches:
  - First 5 (indices 0-4)
  - Middle 5 (around index n/2)
  - Last 5 (indices n-5 to n-1)

Example: For 2500 test vectors, saves indices:
```
[0, 1, 2, 3, 4, 1248, 1249, 1250, 1251, 1252, 2495, 2496, 2497, 2498, 2499]
```

### SPICE Testbenches

Complete, self-contained SPICE netlists ready to simulate:

```spice
* SPICE Testbench for diff_amp
* Generated: 2026-03-07 20:14:32
* Test vector ['inp', 'inn']: [0.9, 0.85]

* Original subcircuit definition
.subckt diff_amp inp inn vout vdd vss
  M1 vout inp nb vss NMOS W=20u L=1u
  M2 nb inn nb vss NMOS W=20u L=1u
  M3 nb nb vdd vdd PMOS W=40u L=1u
  Ibias nb vss DC 100uA
.ends

* Power supplies
VDD vdd 0 DC 1.8
VSS vss 0 DC 0

* Instantiate device under test
Xdut inp inn vout vdd vss diff_amp

* Models
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
.model PMOS PMOS (LEVEL=1 VTO=-0.4 KP=50u)

* Test inputs (from test vector)
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

### Verilog-AMS Testbenches

OSDI-based testbenches for the behavioral model:

```spice
* OSDI testbench for diff_amp

.model osdi_model diff_amp

* Test inputs (from test vector)
Vin0 inp 0 DC 9.000000000000e-01V
Vin1 inn 0 DC 8.500000000000e-01V

* OSDI device instantiation
Nmodel vout inp inn osdi_model

.control
pre_osdi /path/to/diff_amp.osdi
op
print vout
quit
.endc

.end
```

### Test Manifest

JSON file documenting all testbenches:

```json
{
  "block_name": "diff_amp",
  "total_test_vectors": 2500,
  "saved_testbenches": 15,
  "inputs": ["inp", "inn"],
  "outputs": ["vout"],
  "testbenches": [
    {
      "index": 0,
      "inputs": [0.0, 0.0],
      "spice_testbench": "diff_amp/spice/testbench_000.cir",
      "vams_testbench": "diff_amp/verilog_ams/testbench_000.cir"
    },
    {
      "index": 1250,
      "inputs": [0.9, 0.9],
      "spice_testbench": "diff_amp/spice/testbench_1250.cir",
      "vams_testbench": "diff_amp/verilog_ams/testbench_1250.cir"
    }
  ],
  "generated_at": "2026-03-07T20:14:32.123456"
}
```

## Usage

### Enable Testbench Saving

```python
from equivalence_checker import EquivalenceChecker

# Create checker with testbench output directory
checker = EquivalenceChecker(
    abs_tol=1e-3,
    rel_tol=0.05,
    testbench_output_dir='/path/to/testbenches'  # Enable saving
)

# Run equivalence check
result = checker.check_block_equivalence(
    spice_netlist=original_spice,
    verilog_ams_code=generated_verilog,
    block_info=block_metadata,
    test_strategy='grid'
)

# Testbenches are automatically saved to:
# /path/to/testbenches/block_name/...
```

### Disable Testbench Saving (Default)

```python
# Don't save testbenches (default behavior)
checker = EquivalenceChecker(
    abs_tol=1e-3,
    rel_tol=0.05
    # testbench_output_dir=None (default)
)
```

## Benefits

### 1. **Transparency**
- See exactly what test conditions were used
- Understand how equivalence checking works
- Audit the validation process

### 2. **Reproducibility**
- Re-run specific test cases manually
- Reproduce failures for debugging
- Verify results independently

### 3. **Debugging**
- Investigate failing test points
- Compare SPICE vs Verilog-AMS behavior
- Manually tweak and re-simulate

### 4. **Documentation**
- Permanent record of validation tests
- Reference for understanding block behavior
- Training examples for new users

## Example: Manual Re-simulation

To manually re-run a saved testbench:

```bash
# Run SPICE testbench
ngspice testbenches/diff_amp/spice/testbench_050.cir

# Run Verilog-AMS testbench
ngspice testbenches/diff_amp/verilog_ams/testbench_050.cir

# Compare outputs manually
```

## Performance Considerations

- **Minimal overhead**: Only 15 testbenches saved per block (even if 1000s generated)
- **Smart sampling**: Representative coverage across input space
- **On-demand**: Disabled by default, enable only when needed
- **Disk usage**: ~30 KB per block (15 SPICE + 15 Verilog-AMS testbenches)

## Integration with Pipeline

The testbench generation happens automatically during equivalence checking:

```
Pipeline Flow:
1. Extract blocks from SPICE
2. Generate Verilog-AMS models
3. Equivalence checking:
   a. Generate test vectors (e.g., 2500 points)
   b. Compile Verilog-AMS to OSDI
   c. Simulate SPICE with all vectors
   d. Simulate Verilog-AMS with all vectors
   e. ✨ SAVE representative testbenches (15 out of 2500)
   f. Compare results
   g. Generate equivalence report
```

## Files Generated Per Block

```
block_name/
├── spice/                      # SPICE testbenches
│   ├── testbench_000.cir      # ~1-2 KB each
│   ├── testbench_001.cir
│   └── ...                     # ~15 files
├── verilog_ams/                # Verilog-AMS testbenches
│   ├── testbench_000.cir      # ~1 KB each
│   ├── testbench_001.cir
│   └── ...                     # ~15 files
└── test_manifest.json          # ~2-3 KB
```

**Total per block**: ~30-45 KB
**For 10 blocks**: ~300-450 KB
**For 100 blocks**: ~3-4.5 MB

Very reasonable disk usage!

## Summary

✓ **Formalized testbench generation** - No longer ephemeral/temporary
✓ **Organized directory structure** - Easy to navigate
✓ **Representative sampling** - Avoid file explosion
✓ **Complete testbenches** - Ready to simulate
✓ **Metadata included** - Manifest tracks everything
✓ **Optional feature** - Enable when needed
✓ **Minimal overhead** - Smart sampling, low disk usage

This makes the equivalence checking process **transparent, reproducible, and debuggable**!
