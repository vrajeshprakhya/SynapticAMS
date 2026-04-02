# Apple Analog Modeling Standards (placeholder)

Replace this file with the actual client modeling standards document.

## Module Naming

- Use PascalCase: `DiffAmpRx`, `CmlBuffer`, `RingVco`
- Suffix with technology node: `DiffAmpRx_N5` for N5 process
- Differential output modules: append `_Diff`

## Port Order Convention

Outputs before inputs, supplies last:

```verilog
module DiffAmpRx (out_p, out_n, in_p, in_n, vdd, vss);
  output EENet out_p, out_n;
  input  EENet in_p, in_n;
  input  electrical vdd, vss;
```

## Net Discipline

All signal nets must use `EENet` discipline (not `electrical`).
Supply nets use standard `electrical`.

## Parameters

Each parameter must have a comment stating units and physical meaning:

```verilog
parameter real Kvco = 1.5e9;   // Hz/V — VCO gain
parameter real tau  = 1.2e-10; // s   — dominant pole time constant
```

## Clamping

Always clamp outputs to supply rails using named parameters (not magic numbers):

```verilog
V(out) <+ min(voh, max(vol, expression));
```

## File Header

Every .va file must begin with the Apple copyright header:

```
// (c) Apple Inc. — Confidential
// Module: <ModuleName>
// Author: <EID>
// Generated: SynapticAMS vX.Y
```
