# SynapticAMS - SPICE to Verilog-AMS Pipeline

## Overview

Complete pipeline for converting SPICE netlists to Verilog-AMS behavioral models with automatic equivalence checking.

## Directory Structure

```
SynapticAMS/
├── pipeline/                          # Core pipeline modules
│   ├── complete_pipeline.py           # Main pipeline orchestrator
│   ├── circuit_analyzer.py            # Block extraction & classification
│   ├── graph_builder.py               # Netlist graph construction
│   ├── simulation_planner.py          # DC simulation planning
│   ├── verilog_ams_generator.py       # Verilog-AMS code generation
│   ├── fit_transfer_function_dc_sweep.py  # Model fitting
│   └── extract_small_signal_model.py  # Small-signal extraction
│
├── equivalence_checker/               # Equivalence validation
│   ├── equivalence_checker.py         # Multi-mode equivalence checking
│   ├── independence_detector.py       # Input independence analysis
│   └── analysis_mode_selector.py      # Automatic analysis mode selection
│
├── docs/                              # Documentation
│   ├── README.md                      # Original README
│   ├── DC_SWEEP_OPTIMIZATION.md       # DC sweep optimization guide
│   ├── TESTBENCH_GENERATION.md        # Testbench generation docs
│   ├── VERILOG_AMS_DC_SWEEP.md        # Verilog-AMS DC sweep guide
│   ├── MULTI_MODE_EQUIVALENCE_CHECKING.md  # Multi-mode analysis docs
│   ├── INDEPENDENCE_DETECTION_IMPLEMENTATION.md
│   └── IMPLEMENTATION_STATUS.md
│
├── tests/                             # Test files
│   ├── test_complete_pipeline.py
│   ├── test_equivalence_integrated.py
│   ├── test_dc_sweep_optimization.py
│   └── ... (many more test files)
│
├── ngspice_runner.py                  # Ngspice simulation interface
├── pipeline.py                        # Original pipeline (legacy)
└── ai_agent.py                        # AI agent integration
```

## Quick Start

### 1. Basic Pipeline Usage

```python
from pipeline.complete_pipeline import spice_to_verilog_ams

# Read SPICE netlist
with open('my_circuit.cir', 'r') as f:
    netlist = f.read()

# Run pipeline
output_files = spice_to_verilog_ams(netlist, output_dir='./output')

# Generated files:
# - block_0.va, block_1.va, ... (Verilog-AMS modules)
# - equivalence_report.html (validation results)
```

### 2. With Equivalence Checking

```python
from equivalence_checker.equivalence_checker import EquivalenceChecker

checker = EquivalenceChecker(
    abs_tol=1e-3,      # 1mV tolerance
    rel_tol=0.05,       # 5% relative error
    testbench_output_dir='./testbenches'  # Save testbenches
)

result = checker.check_block_equivalence(
    spice_netlist=spice_block,
    verilog_ams_code=generated_verilog,
    block_info=block_metadata,
    test_strategy='grid'
)

print(result)  # Shows pass/fail with detailed metrics
```

### 3. Independence Detection

```python
from equivalence_checker.independence_detector import test_source_independence
from ngspice_runner import NgspiceRunner

runner = NgspiceRunner()

result = test_source_independence(
    netlist=netlist,
    src1='vin',
    src2='ibias',
    output_node='vout',
    runner=runner
)

print(f"Sources coupled: {result['coupled']}")
print(f"Recommendation: {result['recommendation']}")  # '1D' or '2D'
```

## Key Features

### 1. **Automatic Circuit Classification**

The pipeline automatically classifies circuits into three categories:

- **STRUCTURAL_LINEAR**: Pure passive (R/L/C) circuits
- **SMALL_SIGNAL_LINEARIZABLE**: Analog amplifiers (most circuits)
- **NONLINEAR**: Comparators, switches, limiters

### 2. **Topology-Based Analysis Selection**

Automatically determines which analyses are needed:

```python
# Differential pair (no caps) → DC only
# Common-source + cap → DC + AC
# LC filter → DC + AC + Transient
# Comparator → DC + AC + Transient
```

### 3. **DC Sweep Optimization**

Uses native SPICE DC sweep instead of point-by-point simulation:
- **30-100× faster** equivalence checking
- Both SPICE and Verilog-AMS sides optimized
- Automatic fallback for unsupported cases

### 4. **Testbench Generation**

Saves both individual point testbenches and master DC sweep testbenches:
```
testbenches/block_name/
├── master_dc_sweep_spice.cir         # All 2500 points in ONE file
├── master_dc_sweep_verilog_ams.cir   # All 2500 points in ONE file
├── spice/testbench_*.cir             # Individual points for debugging
├── verilog_ams/testbench_*.cir       # Individual points for debugging
└── test_manifest.json                # Metadata
```

### 5. **Multi-Supply & Multi-Current Support**

Automatically extracts voltage and current ranges from netlist:
- Detects all VDD supplies (3.3V, 1.8V, 5V, etc.)
- Detects all current sources
- Dynamic range extraction (no hardcoded values)
- Proper unit parsing (V, mV, A, mA, µA, nA)

### 6. **Independence Detection**

Empirically tests if inputs are coupled or independent:
- Simulation-based coupling analysis
- Automatic 1D vs 2D sweep selection
- Conservative safety margins

## Pipeline Flow

```
Input: SPICE Netlist
    ↓
1. Graph Building (graph_builder.py)
    ↓
2. Circuit Analysis (circuit_analyzer.py)
   - Block extraction
   - Behavior classification
   - Topology analysis
    ↓
3. Simulation Planning (simulation_planner.py)
   - Independence detection
   - DC sweep planning
    ↓
4. DC Simulation (ngspice_runner.py)
   - DC operating point
   - 1D/2D DC sweeps
    ↓
5. Model Fitting (fit_transfer_function_dc_sweep.py)
   - Linear regression
   - Polynomial fitting
   - Piecewise models
    ↓
6. Verilog-AMS Generation (verilog_ams_generator.py)
   - Behavioral model code
   - Parameter extraction
    ↓
7. Equivalence Checking (equivalence_checker.py)
   - DC validation
   - AC validation (planned)
   - Transient validation (planned)
    ↓
Output: Verilog-AMS Modules + Validation Report
```

## Requirements

### Software Dependencies:
- **Python 3.8+**
- **ngspice** with OSDI support
- **OpenVAF** compiler (for Verilog-A compilation)

### Python Packages:
```bash
pip install numpy scipy networkx matplotlib
```

## Testing

Run tests to verify installation:

```bash
# Test complete pipeline
python tests/test_complete_pipeline.py

# Test equivalence checking
python tests/test_equivalence_integrated.py

# Test DC sweep optimization
python tests/test_dc_sweep_optimization.py

# Test independence detection
python tests/test_complete_pipeline_independence.py
```

## Documentation

See `docs/` directory for detailed documentation:

- **DC_SWEEP_OPTIMIZATION.md** - Why DC sweep is 30× faster
- **TESTBENCH_GENERATION.md** - Testbench file formats
- **VERILOG_AMS_DC_SWEEP.md** - OSDI model DC sweep details
- **MULTI_MODE_EQUIVALENCE_CHECKING.md** - AC & Transient validation
- **INDEPENDENCE_DETECTION_IMPLEMENTATION.md** - Coupling analysis

## Performance

| Stage | Old Approach | New Approach | Speedup |
|-------|-------------|--------------|---------|
| SPICE simulation | 2500× DC OP | 1× DC sweep | **~30×** |
| Verilog-AMS simulation | 2500× OSDI OP | 1× OSDI sweep | **~30×** |
| Total equivalence check | ~10 min | ~21 sec | **~29×** |

## Example Circuits

See `examples/` directory for example circuits:
- Differential amplifiers
- Current mirrors
- Common-source amplifiers
- Two-stage operational amplifiers
- RC filters

## Contributing

When adding new features:
1. Add module to appropriate directory (pipeline/ or equivalence_checker/)
2. Add tests to tests/
3. Update relevant documentation in docs/
4. Run existing tests to ensure no regressions

## License

[Your License Here]

## Contact

[Your Contact Info]

---

**Last Updated:** March 8, 2026
**Version:** 2.0 (Post DC Sweep Optimization)
