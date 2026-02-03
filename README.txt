Behavioral Model Extraction — Structural Analysis Pipeline
Purpose

This pipeline analyzes a SPICE netlist structurally (without simulation) to:

Determine which signals actually control circuit behavior

Partition the schematic into behaviorally meaningful blocks

Extract block-level inputs and outputs

Prepare the design for automatic simulation planning and Verilog-AMS generation

At this stage, no SPICE simulations are run.
This pipeline is purely topological + semantic inference.

High-Level Flow
SPICE Netlist
    ↓
Bipartite Signal Graph
    ↓
Constant Net Detection
    ↓
Control-Relevant Device Identification
    ↓
Block Extraction
    ↓
Block I/O Identification

Inputs
Required Input

SPICE netlist

MOSFETs, BJTs, R/L/C, voltage/current sources

Standard SPICE syntax

Optional Inputs

.model definitions (used later for simulation planning)

Named supply rails (e.g. VDD, VSS)

Outputs (So Far)
Artifact	Meaning
Signal graph	Machine-navigable representation of schematic
Constant nets	Nets that cannot carry signal information
Control-relevant devices	Transistors that affect transfer behavior
Blocks	Behaviorally isolated subcircuits
Block inputs	External signals controlling behavior
Block outputs	Observable behavioral results
File-by-File Explanation
graph_builder.py
Purpose

Parses the SPICE netlist and constructs a bipartite graph:

Node types

Net nodes (wires)

Device nodes (MOS, BJT, R, C, L, sources)

Why bipartite?

Because SPICE is inherently:

nets ↔ devices ↔ nets


This representation allows:

Signal reachability analysis

Control path tracing

Safe traversal without ambiguity

Output
graph = {
    "nets": {...},
    "devices": {...},
    "edges": [...]
}

build_signal_graph.py
Purpose

Builds signal connectivity semantics on top of the raw graph.

It enables:

Traversing from a control terminal (gate/base)

Determining where signal can propagate

Distinguishing control vs observation paths

Output

Annotated graph with directional signal interpretation

is_constant_net.py
Purpose

Determines whether a net is constant (cannot carry signal).

Definition (strict)

A net is constant iff all paths from it terminate at:

Ideal voltage sources

Ground

And do not reach:

Control terminals of active devices

Outputs of active devices

Why this matters

Constant nets cannot be behavioral inputs.

Output
constant_nets = {"0", "VDD", "VSS", ...}

is_control_relevant.py
Purpose

Identifies control-relevant transistors.

Definition

A transistor is control-relevant iff:

Its control terminal (gate/base) is connected to a non-constant net

Why this matters

Only these devices:

Define transfer behavior

Need to be modeled behaviorally

Determine required simulations

Output
control_devices = {M1, M5, Q3, ...}

extract_blocks.py
Purpose

Partitions the full circuit into behavioral blocks.

Definition

A block is:

A connected subgraph

Centered around control-relevant devices

Including required bias and load structures

Excluding unrelated passive scaffolding

Why blocks?

Because Verilog-AMS models are modular, not flat.

Output
blocks = [
    Block(id=1, devices={...}, nets={...}),
    Block(id=2, devices={...}, nets={...}),
]

extract_block_io.py
Purpose

Determines inputs and outputs for each block.

Inputs

Nets that:

Enter the block

Are non-constant

Connect to control terminals

Outputs

Nets that:

Leave the block

Are observable

Drive other blocks or top-level pins

Output
BlockIO {
    inputs: {"Vin"},
    outputs: {"Vout"}
}

analyze_blocks.py
Purpose

Coordinates the full structural analysis.

Responsibilities

Run all steps in correct order

Validate consistency

Emit intermediate artifacts for debugging

Output

Final block list

Block I/O mappings

Documentation Files
block_methodology.txt

Explains:

What a “block” means behaviorally

Why blocks exist

How this maps to Verilog-AMS modules

identify_io_of_block.txt

Explains:

How block inputs and outputs are defined

Why bias nets are excluded

Why internal nodes are ignored

pin_classification.txt

Defines:

Supply pins

Signal pins

Bias pins

Ground pins

What This Pipeline Guarantees

After this stage:

✔ You know which signals control behavior
✔ You know what must be simulated
✔ You know what each behavioral module’s interface is
✔ You have zero dependence on heuristics or pattern libraries

What This Pipeline Does NOT Do (Yet)

❌ Run SPICE simulations
❌ Determine linear vs saturating vs switching
❌ Generate Verilog-AMS
❌ Perform frequency or noise analysis

Those happen after this stage.

Next Stage (Preview)

The next pipeline will:

Use block I/O to plan simulations

Run DC OP / DC sweep / transient as needed

Classify behavioral intent

Emit Verilog-AMS templates

Mental Model (Key Insight)

This stage answers:
“What questions should I ask SPICE?”

The next stage answers:
“What did SPICE tell me?”

[Bipartite Graph] 
        │
        ├─> Control relevance → {control_devices, control_terminals}
        │
        └─> Block extraction → {blocks, block_inputs, block_outputs}
        
Simulation Planning:
        simulation_axes = block_inputs ∩ control_terminal_nets









Yes — the bipartite graph is absolutely included, and in fact it is the foundation for both of those graphs. The key is that the later graphs are derived views, not replacements.

Let me pin this down very precisely, because this is where a lot of confusion usually creeps in.

The 3 graph layers (authoritative view)
1️⃣ Bipartite graph (from the SPICE netlist)

This is the source of truth.

Nodes:

device nodes (M1, R3, VDD, …)

net nodes (net:5, net:0, …)

Edges:

device ↔ net

edge annotated with terminal name (G, D, S, etc.)

Purpose

Exact connectivity

Terminal semantics

No interpretation yet

This graph is never thrown away.

Everything else is computed from this graph.

2️⃣ Control information (not a graph, a labeling over the bipartite graph)

This is NOT a separate graph structure.

It is metadata derived from the bipartite graph:

constant_nets ⊆ net nodes

control_relevant_devices ⊆ device nodes

control_terminal_nets ⊆ net nodes

All of these are:

queries

graph walks

classifications

They reference nodes in the bipartite graph directly.

Control info = annotations on the bipartite graph

3️⃣ Full signal graph (derived graph)

This is a projection of the bipartite graph.

Constructed by:

taking the bipartite graph

removing constant nets

keeping all remaining devices

keeping device ↔ net edges

This graph:

is still bipartite

but is pruned

simpler to reason about connectivity

Purpose

block extraction

block IO discovery

This graph exists purely to answer:
“Which things are connected by signals?”

Answering your question directly

Does this include the bipartite graph we built from the netlist at first?

✅ YES — absolutely

But:

The bipartite graph is the base representation

The full signal graph is a filtered view of it

The control info is analysis performed on it

You never “replace” the bipartite graph.

Why we don’t extract blocks directly from the raw bipartite graph

Because the raw bipartite graph contains:

DC rails

bias-only nets

constants

supply trees

Those would:

merge unrelated circuitry into one giant block

destroy useful modular boundaries

So we:

Start with bipartite

Annotate (constant vs variable)

Project into a signal-only graph

Extract blocks

Overlay control info for simulation planning

One-sentence mental model (important)

The bipartite graph is the circuit.
Control relevance is an interpretation of it.
Blocks are a projection of it.
Simulation axes are the intersection of interpretation and projection.
