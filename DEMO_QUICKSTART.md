# SynapticAMS Demo Quickstart Guide

## Prerequisites

1. **Set Anthropic API Key** (for Claude AI refinement):
   ```bash
   export ANTHROPIC_API_KEY="your-key-here"
   ```
   Or add to `~/.bashrc` for persistence:
   ```bash
   echo 'export ANTHROPIC_API_KEY="your-key-here"' >> ~/.bashrc
   source ~/.bashrc
   ```

2. **Verify Dependencies**:
   ```bash
   # Check ngspice
   ngspice --version

   # Check OpenVAF (for OSDI validation)
   openvaf --version

   # Check Python packages
   pip3 list | grep -E "anthropic|numpy|scipy"
   ```

## Running the Warm-Start Demo

### Basic Usage (Default Output Directory)

```bash
cd ~/SynapticAMS
python3 demo_warmstart.py examples/netlists/serdes_cml.cir
```

**Output Location**: `/tmp/synapticams_warmstart_demo_serdes_cml/`

### Custom Output Directory

```bash
# Using --output-dir
python3 demo_warmstart.py examples/netlists/serdes_cml.cir --output-dir ./results

# Using -o shorthand
python3 demo_warmstart.py examples/netlists/serdes_cml.cir -o /path/to/output
```

### With Logging

```bash
# Save full output to log file
python3 demo_warmstart.py examples/netlists/serdes_cml.cir 2>&1 | tee demo.log

# With custom output directory and logging
python3 demo_warmstart.py examples/netlists/serdes_cml.cir -o ./my_results 2>&1 | tee demo.log
```

## What Gets Generated

After running the demo, you'll find:

```
output_directory/
├── baseline_example.va              # Example non-AI model
├── nonai/                            # All non-AI baseline modules
│   ├── *.va                          # Verilog-AMS modules
│   └── *_lut2d.tbl                   # 2D lookup tables
├── refined/                          # AI-refined modules
│   ├── rx_out_p_vs_tx_in_n_rx_tail.va
│   ├── tx_out_n_vs_tx_in_n_rx_tail.va
│   └── ... (all refined modules)
├── comparison_all_modules.txt        # Side-by-side comparison
└── WARMSTART_SUMMARY.txt             # Summary and next steps
```

## Exploring Results

### View All Refined Modules
```bash
OUTPUT_DIR="/tmp/synapticams_warmstart_demo_serdes_cml"
ls -lh $OUTPUT_DIR/refined/*.va
```

### View Specific Module
```bash
cat $OUTPUT_DIR/refined/rx_out_p_vs_tx_in_n_rx_tail.va
```

### View Full Comparison
```bash
cat $OUTPUT_DIR/comparison_all_modules.txt
```

### View Summary
```bash
cat $OUTPUT_DIR/WARMSTART_SUMMARY.txt
```

### Compile All Modules with OpenVAF
```bash
cd $OUTPUT_DIR/refined
for f in *.va; do
    echo "Compiling $f..."
    openvaf "$f" && echo "✓ Success" || echo "✗ Failed"
done
```

## Testing with Different Netlists

The demo works with any SPICE netlist:

```bash
# Simple amplifier
python3 demo_warmstart.py examples/netlists/simple_amp.cir -o ./amp_demo

# SerDes circuit
python3 demo_warmstart.py examples/netlists/serdes_cml.cir -o ./serdes_demo

# Ring oscillator
python3 demo_warmstart.py examples/netlists/ring_osc.cir -o ./osc_demo
```

## Command-Line Help

```bash
python3 demo_warmstart.py --help
```

Output:
```
usage: demo_warmstart.py [-h] [-o OUTPUT_DIR] netlist

SynapticAMS Warm-Start Demo: SPICE → Verilog-AMS conversion

positional arguments:
  netlist               Path to SPICE netlist (.cir file)

optional arguments:
  -h, --help            show this help message and exit
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Output directory for generated files (default:
                        /tmp/synapticams_warmstart_demo_<netlist_name>)

Examples:
  python3 demo_warmstart.py examples/netlists/serdes_cml.cir
  python3 demo_warmstart.py examples/netlists/serdes_cml.cir --output-dir ./results
  python3 demo_warmstart.py examples/netlists/serdes_cml.cir -o /tmp/my_demo
```

## Troubleshooting

### "anthropic module not found"
```bash
pip3 install anthropic
```

### "Cannot connect to Ollama"
The demo auto-detects Anthropic API. If you set `ANTHROPIC_API_KEY`, it will use Claude instead of Ollama.

### "ngspice not found"
```bash
sudo apt install ngspice  # Ubuntu/Debian
brew install ngspice      # macOS
```

### "openvaf not found"
OpenVAF is optional for OSDI validation. Download from: https://github.com/pascalkuthe/OpenVAF/releases

### OSDI Validation Failures
This is a known issue with 2D DC sweeps. The validation attempts to run but may timeout. The generated Verilog-AMS models are still valid - the equivalence checking is just an extra validation step.

## Demo Workflow

The demo performs these steps automatically:

1. **Capability Check**: Verifies all tools are available
2. **Non-AI Baseline**: Runs numeric fitting pipeline
   - Analyzes circuit structure
   - Runs ngspice simulations
   - Fits transfer functions
   - Generates baseline Verilog-AMS modules
3. **AI Refinement**: Refines each module with Claude
   - Skips small-signal models (already optimized)
   - Adds domain knowledge and behavioral modeling
   - Improves accuracy and readability
4. **Comparison**: Generates side-by-side comparisons
5. **Summary**: Creates final report with statistics

## Next Steps After Demo

1. **Review the refined modules** to understand AI improvements
2. **Compile with OpenVAF** to verify Verilog-AMS correctness
3. **Run OSDI equivalence checks** (if OpenVAF is installed)
4. **Integrate into your design flow** by using generated `.va` files in your simulator

## Support

- **GitHub Issues**: https://github.com/your-repo/SynapticAMS/issues
- **Documentation**: See README.md and IMPLEMENTATION_SUMMARY.md
- **Examples**: Check `examples/netlists/` for sample circuits
