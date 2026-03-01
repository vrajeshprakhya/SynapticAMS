# SPICE 3f5 Syntax Support

This document describes the official SPICE 3f5 syntax features supported by the flattener.

## Overview

The SPICE flattener now fully supports the official SPICE 3f5 syntax as defined in the SPICE 3 User's Manual. This ensures compatibility with standard SPICE netlists from any simulator that follows the SPICE 3 specification.

## Implemented Features

### 1. Line Continuation

**Specification**: Lines starting with `+` (plus) in column 1 continue the previous line. SPICE reads from column 2 onwards.

**Example**:
```spice
.SUBCKT LONG_LINE A B C D
+ E F G H
* This defines a subcircuit with 8 ports: A B C D E F G H
```

**Implementation**:
- Processed during file parsing (before any other parsing)
- Handles multi-line continuations (multiple consecutive `+` lines)
- Correctly concatenates from column 2 of continuation lines
- Works with all statement types (.SUBCKT, instances, etc.)

**Code location**: `_process_line_continuation()` method in `spice_flatten.py`

### 2. Comment Syntax

**Specification**: SPICE 3 recognizes two types of comments:
1. Lines starting with `*` (asterisk) - traditional SPICE comment
2. Lines starting with whitespace (spaces or tabs) - SPICE 3 feature

**Example**:
```spice
.SUBCKT BUFFER IN OUT VDD GND
* This is a standard asterisk comment
  This line starts with spaces - also a comment
    More leading spaces - still a comment
	Tab at start - also a comment
M1 OUT IN VDD VDD pmos W=2u L=0.5u
.ENDS
```

**Implementation**:
- Checked at multiple levels:
  - File parsing: Skips comment lines when building top-level lines
  - Subcircuit parsing: Preserves comments within subcircuit definitions
  - Line renaming: Doesn't process comments (returns them unchanged)
- Whitespace check: `line[0].isspace()` (checks first character)
- Works with spaces, tabs, or any whitespace character

**Code locations**:
- `parse_netlist()` - file-level comment filtering
- `_rename_line()` - preserves comments during flattening

## Testing

### Test Suite

The implementation has been tested with:

1. **examples/example_spice3_syntax.sp** - Comprehensive test demonstrating:
   - Multi-line .SUBCKT definitions
   - Multi-line instance calls
   - Leading whitespace comments (spaces and tabs)
   - Combination of both features

2. **Backward compatibility tests**:
   - `test_circuit.sp` - Original hierarchical test (still works)
   - `examples/example_include.sp` - .INCLUDE functionality (still works)
   - `examples/example_lib.sp` - .LIB functionality (still works)

### Test Results

```bash
$ python3 spice_flatten.py examples/example_spice3_syntax.sp examples/example_spice3_syntax_flat.sp

Flattening SPICE netlist: examples/example_spice3_syntax.sp
Found 3 subcircuit definitions:
  - EIGHT_PORT_MUX: 10 ports, 5 lines
  - INVERTER: 4 ports, 6 lines
  - NAND2: 5 ports, 6 lines

Flattened netlist written to: examples/example_spice3_syntax_flat.sp
```

**Verification**:
- ✓ EIGHT_PORT_MUX parsed with 10 ports (line continuation worked)
- ✓ INVERTER and NAND2 have whitespace comments preserved
- ✓ Flattened output maintains all comments correctly
- ✓ No devices created from comment lines

## Known Limitations

The following are **NOT** part of official SPICE 3f5 and are therefore **NOT** supported:

### 1. Inline Comments with `$`

```spice
M1 OUT IN VDD VDD pmos W=2u L=0.5u  $ This is NOT SPICE 3
```

**Status**: Not implemented (ngspice extension)

The `$` delimiter for inline comments is an **ngspice-specific extension**, not part of the official SPICE 3f5 specification. If your netlist uses `$` comments, they will be treated as part of the line content.

### 2. Parameterized Subcircuits

```spice
.SUBCKT RESISTOR_DIV IN OUT GND PARAMS: R1=1k R2=1k
```

**Status**: Not implemented (simulator-specific extension)

The `PARAMS:` keyword is a **simulator-specific extension** (used by ngspice, LTspice, and others) but is not part of official SPICE 3f5. Parameter values in curly braces `{R1}` will also not be evaluated.

### 3. Expression Evaluation

```spice
R1 A B {R_VAL * 2}
.PARAM R_VAL=10k
```

**Status**: Not implemented (simulator-specific)

Parameter expressions and `.PARAM` statements are simulator extensions. The flattener treats these as literal text.

## Design Decisions

### Why Preserve Comments in Flattened Output?

The flattener preserves whitespace comments (and all comments) in the output for several reasons:

1. **Traceability**: Comments help users understand the flattened netlist structure
2. **Debugging**: Original comments provide context for troubleshooting
3. **SPICE Compliance**: Comments are valid SPICE syntax and don't affect simulation

Comments inside subcircuits are copied to the flattened instances, maintaining documentation.

### Processing Order

1. **File reading**: Read raw lines from file
2. **Line continuation**: Join lines starting with `+`
3. **Comment detection**: Identify and handle comment lines
4. **Parsing**: Parse .SUBCKT definitions, instances, and control statements
5. **Flattening**: Replace instances with subcircuit contents

This order ensures that:
- Multi-line statements are seen as single logical lines
- Comments are correctly identified before parsing
- All SPICE 3 syntax is properly handled

## Future Enhancements

Possible future additions (not in current scope):

1. **ngspice extensions** (if requested):
   - Inline comments with `$`
   - `.GLOBAL` node declarations
   - `.PARAM` with expression evaluation

2. **Advanced features**:
   - Subcircuit parameter support (`PARAMS:`)
   - Expression evaluation
   - Conditional compilation

These would be added only if there's clear user demand, as they go beyond the official SPICE 3f5 specification.

## References

- **SPICE 3 User's Manual** - Section 2: SPICE3 Input Syntax
  - Line continuation: Section 2.1
  - Comments: Section 2.2.3
  - Subcircuits: Section 2.4

## Verification Summary

| Feature | Status | Test File | Result |
|---------|--------|-----------|--------|
| Line continuation (+) | ✓ Implemented | example_spice3_syntax.sp | Pass |
| Asterisk comments (*) | ✓ Implemented | All test files | Pass |
| Whitespace comments | ✓ Implemented | example_spice3_syntax.sp | Pass |
| Multi-line .SUBCKT | ✓ Implemented | example_spice3_syntax.sp | Pass |
| Multi-line instances | ✓ Implemented | example_spice3_syntax.sp | Pass |
| Backward compatibility | ✓ Maintained | test_circuit.sp | Pass |

All official SPICE 3f5 syntax features are now fully supported.

---

**Version**: 2.1
**Date**: 2026-02-28
**Author**: SynapticAMS Project
