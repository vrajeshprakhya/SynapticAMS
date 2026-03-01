# SPICE Subcircuit Resolver (Flattener)

A Python tool that flattens hierarchical SPICE netlists by resolving all `.SUBCKT` definitions and replacing subcircuit instances with their actual device-level implementations.

## Quick Start

```bash
python3 spice_flatten.py <input_netlist.sp> [output_netlist.sp]
```

**Example**:
```bash
python3 spice_flatten.py test_circuit.sp output_flat.sp
```

## What It Does

The tool takes a hierarchical SPICE netlist like this:

```spice
.SUBCKT NAND2 A B OUT VDD GND
M1 OUT A VDD VDD pmos W=2u L=0.5u
M2 OUT B VDD VDD pmos W=2u L=0.5u
M3 OUT A net1 GND nmos W=2u L=0.5u
M4 net1 B GND GND nmos W=2u L=0.5u
.ENDS

X1 sig_a sig_b out VDD GND NAND2
```

And converts it to a flat netlist:

```spice
M_X1_1 out sig_a VDD VDD pmos W=2u L=0.5u
M_X1_2 out sig_b VDD VDD pmos W=2u L=0.5u
M_X1_3 out sig_a X1_net1 GND nmos W=2u L=0.5u
M_X1_4 X1_net1 sig_b GND GND nmos W=2u L=0.5u
```

## Features

- **Hierarchical flattening**: Supports arbitrary nesting depth
- **External file support**: Processes `.INCLUDE` and `.LIB` statements
- **File-relative path resolution**: Paths resolved relative to the including file (standard SPICE behavior)
- **Library sections**: Supports `.LIB 'file.lib' SECTION_NAME` syntax
- **Circular include protection**: Tracks processed files to avoid infinite loops
- **SPICE-compliant naming**: Device names preserve type letter (M, Q, D, R, C, etc.)
- **Port mapping**: Correctly maps formal to actual parameters
- **Global node preservation**: VDD, GND, VSS remain unchanged
- **Model name protection**: Model names (pmos, nmos, etc.) are never renamed
- **Unique name generation**: Hierarchical prefixes prevent name collisions

## SPICE 3f5 Syntax Support

The tool fully supports official SPICE 3f5 syntax features:

### Line Continuation
Lines starting with `+` in column 1 continue the previous line, reading from column 2 onwards:

```spice
.SUBCKT MULTI_PORT A B C D
+ E F G H
* Defines a subcircuit with 8 ports: A B C D E F G H
```

Instance definitions can also span multiple lines:

```spice
X1 sig_a sig_b sig_c sig_d
+ sig_e sig_f sig_g sig_h
+ MULTI_PORT
```

### Comment Syntax
The tool recognizes all standard SPICE 3f5 comment formats:

1. **Asterisk comments**: Lines starting with `*` are comments
2. **Leading whitespace**: Lines starting with whitespace (spaces or tabs) are treated as comments

```spice
.SUBCKT BUFFER IN OUT VDD GND
* This is a standard comment
  This is also a comment (leading spaces)
	This too (leading tab)
M1 OUT IN VDD VDD pmos W=2u L=0.5u
.ENDS
```

### Limitations
- **Inline comments** (`$` delimiter) are NOT supported - this is an ngspice extension, not part of official SPICE 3f5
- **Parameterized subcircuits** (`PARAMS:` keyword) are NOT supported - this is a simulator-specific extension

## Verification

The tool has been verified by simulating both hierarchical and flattened versions of the same circuit in ngspice:

- **Test circuit**: D Flip-Flop chain (3-level hierarchy)
- **Simulation points**: 1140
- **Maximum voltage difference**: 0.0 V (exact match)
- **Conclusion**: ✓ Flattening preserves circuit behavior exactly

See `VERIFICATION_SUMMARY.md` for detailed results.

## Files in This Directory

### Core Tool
- **spice_flatten.py** - Main flattening tool

### Test Circuits
- **test_circuit.sp** - Original hierarchical test circuit
- **test_circuit_flat_v2.sp** - Flattened version
- **test_circuit_hierarchical.sp** - Hierarchical with MOSFET models (sim-ready)
- **test_circuit_sim_v2.sp** - Flattened with MOSFET models (sim-ready)

### Simulation Results
- **hierarchical_results.txt** - Text output from hierarchical simulation
- **flattened_results.txt** - Text output from flattened simulation
- **test_hierarchical.raw** - Binary waveform data (hierarchical)
- **test_circuit_sim.raw** - Binary waveform data (flattened)

### Analysis Scripts
- **compare_text_results.py** - Compares simulation outputs to verify correctness

### Documentation
- **VERIFICATION_SUMMARY.md** - Detailed verification report
- **README.md** - This file

## How It Works

### 1. Parsing
The tool parses the input netlist and identifies:
- All `.SUBCKT` definitions
- All subcircuit instances (lines starting with 'X')
- Top-level circuit elements

### 2. Flattening
For each subcircuit instance:
1. Find the matching `.SUBCKT` definition
2. Create port-to-net mapping (formal params → actual connections)
3. Copy all devices from the subcircuit
4. Rename devices with hierarchical prefix: `DeviceType_InstancePath_OriginalName`
5. Rename internal nodes with instance prefix
6. Map port nodes to actual connections
7. Preserve global nodes (VDD, GND, etc.)
8. Keep model names unchanged

### 3. Recursion
Nested subcircuits are handled recursively:
- Each level gets a unique hierarchical prefix
- Inner instances are flattened first
- Prefixes accumulate: `X1` → `X_DFF1_X1` → `X_DFF1_X1_X2`

## Device Naming Convention

Original hierarchical path:
```
Top → X_DFF1 → X1 (NAND2) → M1 (MOSFET)
```

Flattened device name:
```
M_X_DFF1_X1_1
│ │         │
│ │         └─ Original device number
│ └─────────── Instance hierarchy
└───────────── Device type (preserved at start)
```

## Supported Device Types

- **M** - MOSFET (4 nodes + model)
- **Q** - BJT (3 nodes + model)
- **D** - Diode (2 nodes + model)
- **R** - Resistor (2 nodes)
- **C** - Capacitor (2 nodes)
- **L** - Inductor (2 nodes)
- **V** - Voltage source (2 nodes)
- **I** - Current source (2 nodes)
- And other standard SPICE devices

## External File Support

### .INCLUDE Statement

The tool supports standard `.INCLUDE` (or `.INC`) statements:

```spice
.INCLUDE "models/transistors.sp"
.INCLUDE '../pdk/devices.lib'
.INC subcircuits.sp
```

**Path Resolution**:
1. Absolute paths used as-is: `/usr/local/pdk/models.lib`
2. Relative paths resolved relative to the **file being parsed** (not working directory)
3. Fallback to top-level netlist directory

**Example**:
```
Project structure:
/home/user/project/
├── top.sp                    ← Main file
├── blocks/
│   └── amplifier.sp
└── models/
    └── transistors.lib

In top.sp:
.INCLUDE "blocks/amplifier.sp"    → /home/user/project/blocks/amplifier.sp

In blocks/amplifier.sp:
.INCLUDE "../models/transistors.lib"  → /home/user/project/models/transistors.lib
```

### .LIB Statement

Library files with optional section names:

```spice
.LIB 'models.lib' TYPICAL
.LIB "pdk/devices.lib" TT
.LIB 'resistors.lib'           ← No section, processes entire file
```

**Library Sections**:
```spice
* In models.lib:
.LIB TYPICAL
.SUBCKT NMOS_TYP D G S B
  * Typical corner models
.ENDS
.ENDL

.LIB FAST
.SUBCKT NMOS_FAST D G S B
  * Fast corner models
.ENDS
.ENDL
```

When you use `.LIB 'models.lib' TYPICAL`, only subcircuits from the TYPICAL section are extracted.

### Circular Include Protection

The tool tracks all processed files and skips files that have already been included, preventing infinite loops from circular dependencies.

## Limitations

- Assumes standard SPICE syntax
- Some simulator-specific extensions may not be handled
- Does not support search paths from environment variables (e.g., `SPICE_LIB_DIR`)

## Example Usage

### Flatten a circuit
```bash
python3 spice_flatten.py my_circuit.sp my_circuit_flat.sp
```

### View flattening statistics
The tool prints information during execution:
```
Flattening SPICE netlist: my_circuit.sp
Found 5 subcircuit definitions:
  - INV: 4 ports, 2 lines
  - NAND2: 5 ports, 4 lines
  - NOR2: 5 ports, 4 lines
  - DFF: 6 ports, 12 lines
  - COUNTER: 8 ports, 25 lines

Flattened netlist written to: my_circuit_flat.sp
```

### Simulate and compare
```bash
# Simulate hierarchical version
ngspice -b test_circuit_hierarchical.sp

# Simulate flattened version
ngspice -b test_circuit_sim_v2.sp

# Compare results
python3 compare_text_results.py
```

## Verified Correctness

The tool has been verified by:
1. Creating a hierarchical test circuit (DFF chain)
2. Flattening it with the tool
3. Simulating both versions in ngspice
4. Comparing all output waveforms

**Result**: Both simulations produce **identical** outputs (0.0 V difference at all 2280 comparison points).

This confirms the flattening preserves:
- Circuit topology
- Device parameters
- Node connectivity
- Electrical behavior

## Recent Updates

### v2.1 - 2026-02-28: SPICE 3f5 Syntax Support

Added full support for official SPICE 3f5 syntax features:

**What's New:**
- ✓ Line continuation with `+` in column 1
- ✓ Leading whitespace as comment (spaces/tabs at line start)
- ✓ Proper handling of multi-line subcircuit definitions
- ✓ Proper handling of multi-line instance calls

**Examples:**
```spice
* Line continuation
.SUBCKT LONG A B C D
+ E F G H
.ENDS

* Leading whitespace comments
.SUBCKT BUFFER IN OUT
  This is a comment
M1 OUT IN VDD VDD pmos
.ENDS
```

### v2.0 - 2026-02-28: External File Support

Added support for `.INCLUDE` and `.LIB` statements:

**What's New:**
- ✓ `.INCLUDE` statement processing
- ✓ `.LIB` statement with section support
- ✓ File-relative path resolution (standard SPICE behavior)
- ✓ Circular include protection
- ✓ Working examples in `examples/` directory

**Try the Examples:**
```bash
# Test .INCLUDE functionality
python3 spice_flatten.py examples/example_include.sp examples/output.sp

# Test .LIB with section selection
python3 spice_flatten.py examples/example_lib.sp examples/output_lib.sp
```

See `examples/README.md` for detailed documentation and more examples.

## Technical Implementation Notes

### SPICE 3f5 Compliance

The flattener fully implements the official SPICE 3f5 specification:

**Line Continuation Processing**:
- Implemented in `_process_line_continuation()` method
- Processes all files before parsing (first step after reading)
- Concatenates lines starting with `+` from column 2 onwards
- Handles multiple consecutive continuation lines

**Comment Handling**:
- Asterisk comments (`*`) - traditional SPICE
- Leading whitespace comments - SPICE 3f5 feature
- Checked at multiple levels: file parsing, subcircuit parsing, line processing
- Comments preserved in flattened output for documentation

**Not Implemented** (simulator extensions, not SPICE 3f5):
- Inline comments with `$` (ngspice)
- `PARAMS:` keyword (ngspice, LTspice)
- `.PARAM` expression evaluation (simulator-specific)

See `SPICE3_SYNTAX.md` for detailed technical documentation.

### Code Structure

**Main Classes**:
- `SpiceFlattener` - Main flattening engine
- `SubcktDefinition` - Represents a subcircuit

**Key Methods**:
- `parse_netlist()` - Parses SPICE files with line continuation and comment handling
- `_process_line_continuation()` - Joins multi-line statements
- `_flatten_instance()` - Recursively flattens subcircuit instances
- `_rename_line()` - Renames devices and nodes while preserving comments
- `_rename_node()` - Maps ports and prefixes internal nodes

**Processing Pipeline**:
1. Read file → 2. Process line continuation → 3. Filter comments → 4. Parse .SUBCKT and instances → 5. Flatten hierarchy → 6. Write output

## Author

Created as part of the SynapticAMS project.

## License

[Add your license here]
