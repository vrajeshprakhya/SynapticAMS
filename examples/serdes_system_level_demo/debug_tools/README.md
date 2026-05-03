# Debug Tools

Helper scripts and utilities for debugging the SerDes model generation pipeline.

## Tools

### `parse_raw.py`
Parse ngspice binary .raw files and extract waveform data.

**Usage:**
```bash
python3 parse_raw.py /path/to/file.raw
```

**Features:**
- Extracts variable names and data points
- Displays first/last timepoints
- Supports binary raw format from ngspice

---

### `test_baseline_validation.py`
Test baseline model validation against fixed SPICE reference.

**Usage:**
```bash
python3 test_baseline_validation.py
```

**What it does:**
- Reads baseline Verilog-AMS model
- Reads SPICE netlist
- Runs transient validation
- Prints validation metrics (error, correlation)

---

### `use_ai_model_directly.sh`
Directly use AI-refined model without validation loop.

**Usage:**
```bash
./use_ai_model_directly.sh
```

**Features:**
- Compiles AI model with OpenVAF
- Runs simulation with OSDI
- Skips validation step

---

### `test_system_model.sh`
Test system-level model extraction.

**Usage:**
```bash
./test_system_model.sh
```

**What it does:**
- Extracts system-level model from netlist
- Compiles with OpenVAF
- Runs basic simulation
- Checks output

## Tips

1. **Parse simulation results:**
   ```bash
   python3 parse_raw.py simulation.raw > results.txt
   ```

2. **Quick model validation:**
   ```bash
   python3 test_baseline_validation.py | grep "RESULT"
   ```

3. **Test without full pipeline:**
   ```bash
   ./use_ai_model_directly.sh
   ```
