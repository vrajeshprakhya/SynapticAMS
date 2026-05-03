# Solution: Extracting ONE System-Level Model from Integrated SerDes Netlist

## Problem
The original pipeline was generating **10 separate models** for internal signal relationships within the SerDes circuit, but you needed **ONE system-level model** representing the complete system: `final_out = f(tx_p_src, tx_n_src)`.

## Root Cause
The pipeline's automatic block discovery (`analyze_blocks()` in `complete_pipeline.py`) is designed to discover **all functional blocks** in a circuit and model their relationships separately. For the flattened SerDes netlist, it found 10 internal relationships:

```
X_CTLE_s1_vs_tx_n_src.va
X_CTLE_s1_vs_tx_p_src.va
X_CTLE_s2_vs_tx_n_src.va
X_CTLE_s2_vs_tx_p_src.va
ctle_outn_vs_tx_n_src.va
ctle_outn_vs_tx_p_src.va
ctle_outp_vs_tx_n_src.va
ctle_outp_vs_tx_p_src.va
small_signal_vs_M_X_CTLE_1.va
small_signal_vs_M_X_CTLE_2.va
```

**None of these represented the complete system-level transfer function!**

## Solution
Created a **custom extraction workflow** that bypasses automatic block discovery and manually specifies the system-level I/O relationship to extract.

### Key Components

#### 1. System-Level Extractor (`/tmp/extract_system_model.py`)
- Manually specifies inputs (`tx_p_src`, `tx_n_src`) and output (`final_out`)
- Runs 2D DC sweep to characterize the complete system
- Fits ONE transfer function for the system-level relationship
- Generates ONE Verilog-AMS behavioral model

```bash
python3 /tmp/extract_system_model.py /tmp/flattened_serdes.cir /tmp/output_dir
```

#### 2. Integrated AI Refinement Demo (`/tmp/demo_system_level_refinement.py`)
- Combines system-level extraction with the 3-pass AI validation loop
- Extract baseline → AI refine → Validate → Error correction
- Generates ONE final model, not multiple internal models

```bash
/tmp/run_system_level_demo.sh
```

## Results

### Before (Original Pipeline)
```
Output: 10 models (all internal CTLE relationships)
- X_CTLE_s1_vs_tx_n_src
- ctle_outp_vs_tx_p_src
- ... (8 more internal models)
NO system-level model!
```

### After (Custom System-Level Extraction)
```
Output: 1 model (complete system)
- serdes_rx_system.va
  Inputs:  tx_p_src, tx_n_src (differential)
  Output:  final_out

✓ Compiles with OpenVAF
✓ Represents complete SerDes RX chain
✓ Can be refined with AI validation loop
```

## Generated Files

### Final Model
```
/tmp/serdes_final_model/final/serdes_rx_system.va
```

This is the ONE behavioral model you requested, representing:
```
Signal Flow: TX → Channel → CTLE → VGA → Summer → final_out
Transfer Function: final_out = f(tx_p_src, tx_n_src)
```

### Directory Structure
```
/tmp/serdes_final_model/
├── baseline/
│   └── serdes_rx_system.va         # Numerically-fitted baseline model
├── pass1/
│   └── serdes_rx_system.va         # AI-refined version (Pass 1)
├── pass3/
│   └── serdes_rx_system.va         # Error-corrected version (if successful)
├── final/
│   └── serdes_rx_system.va         # Final validated model
└── testbenches/
    └── serdes_rx_system/           # DC sweep validation testbenches
```

## Usage

### Run System-Level Extraction
```bash
# Quick extraction (baseline only)
cd /home/vrajeshprakhya/SynapticAMS
export PYTHONPATH=/home/vrajeshprakhya/SynapticAMS:$PYTHONPATH
python3 /tmp/extract_system_model.py /tmp/flattened_serdes.cir /tmp/output_dir
```

### Run with AI Refinement
```bash
# Complete workflow (baseline + AI refinement + validation)
/tmp/run_system_level_demo.sh
```

### Compile the Model
```bash
openvaf /tmp/serdes_final_model/final/serdes_rx_system.va
```

### Use in ngspice Simulation
```spice
.osdi /tmp/serdes_final_model/final/serdes_rx_system.osdi

X_SERDES_MODEL tx_p tx_n recovered_out serdes_rx_system
```

## Why This Works

### Original Problem: Block Discovery Sees Everything
```
Netlist → Flattening → Parsing → analyze_blocks()
                                       ↓
                          Discovers ALL signal paths
                                       ↓
                          Creates 10 models for internal relationships
```

### New Approach: Manual I/O Specification
```
Netlist → Manual I/O Spec → DC Sweep → Fit → Generate VA
   (tx_p_src, tx_n_src, final_out)
                                              ↓
                                      ONE system-level model
```

By **bypassing the automatic discovery** and **manually specifying** which I/O relationship to extract, we get exactly what you need: **ONE model from ONE netlist**.

## Next Steps

1. **View the final model:**
   ```bash
   cat /tmp/serdes_final_model/final/serdes_rx_system.va
   ```

2. **Run the complete demo on any netlist:**
   ```bash
   python3 /tmp/demo_system_level_refinement.py <your_netlist.cir> -o <output_dir>
   ```

3. **Integrate into your workflow:**
   - Copy `/tmp/extract_system_model.py` to your project
   - Copy `/tmp/demo_system_level_refinement.py` to your project
   - Modify the I/O specifications for different systems

## Key Takeaway

**You now have ONE behavioral model from ONE integrated SerDes netlist, regardless of the number of internal blocks or pipeline iterations!**

The solution:
- ✓ Extracts system-level I/O only
- ✓ Generates ONE model (not 10)
- ✓ Works with AI refinement and validation
- ✓ Compiles with OpenVAF
- ✓ Can be used in SPICE simulations
