# SPICE Flattener Examples

This directory contains examples demonstrating `.INCLUDE`, `.LIB`, and SPICE 3f5 syntax features.

## Directory Structure

```
examples/
├── lib/
│   ├── basic_gates.sp      - Library of basic logic gates
│   └── corners.lib         - Process corner models (TYPICAL, FAST, SLOW)
├── example_include.sp      - Demonstrates .INCLUDE usage
├── example_lib.sp          - Demonstrates .LIB with section selection
├── example_spice3_syntax.sp - Demonstrates SPICE 3f5 line continuation and comments
└── README.md               - This file
```

## Example 1: Using .INCLUDE

**File**: `example_include.sp`

This example shows how to include subcircuit definitions from an external file using `.INCLUDE`:

```spice
.INCLUDE "lib/basic_gates.sp"
```

The path is resolved **relative to the file** containing the `.INCLUDE` statement.

**Run it**:
```bash
cd ~/SynapticAMS/subckt_resolver
python3 spice_flatten.py examples/example_include.sp examples/example_include_flat.sp
```

**Expected output**:
```
Flattening SPICE netlist: examples/example_include.sp
  Including: lib/basic_gates.sp -> /path/to/examples/lib/basic_gates.sp
Found 2 subcircuit definitions:
  - INV_TEST: 4 ports, 2 lines
  - NAND2_TEST: 5 ports, 4 lines

Flattened netlist written to: examples/example_include_flat.sp
```

## Example 2: Using .LIB with Sections

**File**: `example_lib.sp`

This example shows how to load a specific section from a library file:

```spice
.LIB 'lib/corners.lib' TYPICAL
```

The library file `corners.lib` contains three sections:
- **TYPICAL** - Typical process corner (vto=0.7)
- **FAST** - Fast process corner (vto=0.6)
- **SLOW** - Slow process corner (vto=0.8)

Only the specified section is loaded.

**Run it**:
```bash
cd ~/SynapticAMS/subckt_resolver
python3 spice_flatten.py examples/example_lib.sp examples/example_lib_flat.sp
```

**Expected output**:
```
Flattening SPICE netlist: examples/example_lib.sp
  Loading library: lib/corners.lib (section: TYPICAL) -> /path/to/examples/lib/corners.lib
Found 1 subcircuit definitions:
  - NMOS_TYP: 4 ports, 3 lines

Flattened netlist written to: examples/example_lib_flat.sp
```

## Testing Different Corners

To test different process corners, modify `example_lib.sp`:

```spice
* For fast corner
.LIB 'lib/corners.lib' FAST

* For slow corner
.LIB 'lib/corners.lib' SLOW
```

## Path Resolution

The tool resolves paths in this order:

1. **Absolute paths** - Used as-is
   ```spice
   .INCLUDE "/usr/local/pdk/models.sp"
   ```

2. **Relative to current file** - Primary method (standard SPICE)
   ```spice
   .INCLUDE "../models/transistors.sp"
   .INCLUDE "lib/gates.sp"
   ```

3. **Relative to top-level file** - Fallback
   ```spice
   .INCLUDE "shared/common.sp"
   ```

## Example 3: SPICE 3f5 Syntax Features

**File**: `example_spice3_syntax.sp`

This example demonstrates official SPICE 3f5 syntax features:

### Line Continuation
Lines starting with `+` in column 1 continue the previous line:

```spice
.SUBCKT EIGHT_PORT_MUX A B C D
+ E F G H
+ VDD GND
```

Instance calls can also span multiple lines:

```spice
X1 sig_a sig_b sig_c sig_d
+ sig_e sig_f sig_g sig_h
+ VDD 0
+ EIGHT_PORT_MUX
```

### Leading Whitespace Comments
Lines starting with spaces or tabs are treated as comments:

```spice
.SUBCKT INVERTER IN OUT VDD GND
  This line starts with spaces - it's a comment
    This one has even more leading spaces
	This line starts with a tab - also a comment
M1 OUT IN VDD VDD pmos W=2u L=0.5u
.ENDS
```

**Run it**:
```bash
cd ~/SynapticAMS/subckt_resolver
python3 spice_flatten.py examples/example_spice3_syntax.sp examples/example_spice3_syntax_flat.sp
```

**Expected output**:
```
Flattening SPICE netlist: examples/example_spice3_syntax.sp
Found 3 subcircuit definitions:
  - EIGHT_PORT_MUX: 10 ports, 5 lines
  - INVERTER: 4 ports, 6 lines
  - NAND2: 5 ports, 6 lines

Flattened netlist written to: examples/example_spice3_syntax_flat.sp
```

The flattened output will:
- Correctly parse multi-line subcircuit definitions
- Correctly parse multi-line instance calls
- Preserve whitespace comments as-is (not treat them as device definitions)

## Creating Your Own Examples

### Structure
```
myproject/
├── main.sp
├── blocks/
│   └── amplifier.sp
└── lib/
    └── devices.sp
```

### In main.sp
```spice
.INCLUDE "blocks/amplifier.sp"
```

### In blocks/amplifier.sp
```spice
.INCLUDE "../lib/devices.sp"
```

All paths work correctly because they're resolved **relative to the file being parsed**, not the working directory.

## Verification

After flattening, you can verify the result by:

1. **Checking subcircuit resolution**:
   ```bash
   grep "Begin subcircuit" examples/example_include_flat.sp
   ```

2. **Ensuring no X instances remain** (all flattened):
   ```bash
   grep "^X" examples/example_include_flat.sp
   # Should only show comments starting with "* Flattened instance: X..."
   ```

3. **Checking device names** (should start with device type):
   ```bash
   grep "^M_" examples/example_include_flat.sp
   # All MOSFETs start with M_
   ```
