# SynapticAMS Product Plan: Multi-Client RAG + System Integration + Cleanup

## Context

SynapticAMS converts SPICE netlists to Verilog-AMS behavioral models. The non-AI
pipeline (graph analysis, ngspice sweeps, numeric fitting) is largely solid.
Three major gaps block making this a production multi-client product:

1. No client context — AI generates generic code with no knowledge of Apple's EENet,
   Nvidia's naming conventions, or any company's modeling standards
2. No standalone testbench export — equivalence_checker builds testbenches internally
   but clients cannot take them to Cadence/Virtuoso
3. No system integration — multiple .va blocks are generated with no top-level assembly

---

## Where AI Should Actually Be Used (5 Insertion Points)

These are the places where AI is uniquely justified over non-AI rules.

| # | Where | What AI Does | Why Non-AI Fails |
|---|-------|-------------|-----------------|
| 1 | Pre-non-AI: topology classification | Identifies circuit type (diff pair, current mirror, LDO, etc.), selects model strategy | Non-AI graph analysis is structural; it can't reason about analog intent |
| 2 | Pre-generation: net type resolution | Maps client-custom nets (EENet, etc.) to Verilog-AMS disciplines via RAG context | Can't enumerate all proprietary net types across the industry |
| 3 | Generation: style-aware VA synthesis | Generates code in client's preferred style using retrieved examples | Style is semantic, not syntactic — rules can't generalize |
| 4 | Refinement: loss diagnosis | Explains *why* NRMSE is high, which region fails, what physics is missing | Current loop just says "NRMSE=X, try again" — no reasoning |
| 5 | Post-generation: system integration review | Reviews auto-assembled top-level connections, flags mismatches | Heuristic name-matching produces ambiguous results that need AI judgment |

**Current AI use**: Only #3 (generation) and a partial #4 (refinement without context).
**The user's plan** (RAG DB + topology recognition + style adaptation) is correct and fills #1, #2, #3.

---

## Plan

### P1 — Per-Client RAG Database (Highest Priority)

**Architecture: file-system-first, vector DB as upgrade path**

No vector DB on day one. Enterprise client corpora are small (5–20 docs).
Keyword-ranked retrieval over a local directory is sufficient and has zero
additional dependencies. Vector search can be dropped in later behind the same
interface.

**Directory structure:**
```
clients/
  apple/
    config.json           # name, preferred_discipline, style_summary, max_context_docs
    discipline_files/     # .vams custom net definitions (e.g., EENet.vams)
    style_docs/           # .md/.txt modeling standards and naming conventions
    example_models/       # .va reference models in client's preferred style
  nvidia/
    config.json
    ...
```

**New files:**
- `rag/__init__.py` — empty package marker
- `rag/client_store.py` — `ClientStore` class
  - `get_context(circuit_hints: dict) → str` — keyword-ranked retrieval, returns
    formatted `## Client Context` section ready for AI prompt injection
  - `circuit_hints` = `{module_name, device_types, block_type}` — all available
    from `parse_netlist()` output
  - No new dependencies (stdlib only: `pathlib`, `json`, `re`)

**Modifications to existing files:**

`ai_agent.py`:
- Add `_build_system_prompt(client_context=None) → str` after line 66
  Appends `## Client-Specific Requirements\n{client_context}` to `SYSTEM_PROMPT`
- Extend `generate()` (line 577) and `refine()` (line 590) with `client_context=None` kwarg
- Pass `_build_system_prompt(client_context)` instead of `SYSTEM_PROMPT` to `agent.chat()`
- All existing call sites continue to work (keyword-only, default None)

`pipeline.py`:
- Add `client_id=None` to `run_pipeline()` signature (line 857)
- After `parse_netlist()` (~line 885): load `ClientStore(client_id).get_context(hints)`
- Pass `client_context` through to `generate()` and `refine()` calls

`pipeline_ext/complete_pipeline.py`:
- Add `client_id=None` to `spice_to_verilog_ams()` signature
- Same RAG lookup, pass context into any AI calls

---

### P2 — Standalone Testbench Export (Nearly Free)

**Current state:** `EquivalenceChecker._save_testbenches()` exists at line 1274 of
`equivalence_checker/equivalence_checker.py`. It generates organized ngspice testbenches
per block when `testbench_output_dir` is passed to the constructor. It is *currently
never activated* because `OSDIEquivalenceChecker()` is instantiated at line 801 of
`complete_pipeline.py` without this argument.

**Fix — one line change in `pipeline_ext/complete_pipeline.py` line 801:**
```python
# Before:
osdi_checker = OSDIEquivalenceChecker(abs_tol=0.01, rel_tol=0.05)
# After:
tb_dir = Path(output_dir) / "testbenches"
osdi_checker = OSDIEquivalenceChecker(abs_tol=0.01, rel_tol=0.05,
                                       testbench_output_dir=str(tb_dir))
```

**New file: `testbench_exporter.py`**
Standalone export for the AI-only pipeline path (`pipeline.py`), which doesn't
use `EquivalenceChecker` directly. Wraps `_build_spice_testbench()` and
`_build_osdi_dc_sweep_testbench()` as an export-only operation (no comparison run).

Output structure per run:
```
output_dir/
  testbenches/
    {block_name}/
      testbench.sp         # ngspice-compatible standalone testbench
      run_testbench.sh     # convenience script
```

**Note:** Cadence Spectre compatibility would require a Spectre netlist formatter —
separate feature, not in this plan.

---

### P3 — System Integration / Top-Level Assembly

**Current state:** Zero code exists. `complete_pipeline.py` generates N independent
`.va` files with no top-level assembly.

**New file: `system_assembler.py`**

```python
def assemble_system(va_files: List[Path], output_dir: str,
                    system_name: str = "system_top",
                    client_id: str = None) -> Path
```

**Algorithm:**
1. Parse each `.va` file — extract module name and port list (direction + name)
   using regex on `module NAME(ports)` and `input/output electrical PORT`
2. Build a connectivity graph — match `output` ports of block A to `input` ports
   of block B using:
   - **Name matching**: `out`↔`in`, `vout`↔`vin`, `output`↔`input`
   - **Net name matching**: if both came from `complete_pipeline.py`, use the
     circuit analyzer's `block_info` inputs/outputs sets (same net names)
3. Emit `system_top.va`:
   - Internal `electrical` wires for matched ports
   - Module instantiations for each block
   - `// TODO: connect <port>` stubs for unresolved ports (engineer reviews)
4. Emit `instantiation_list.txt` — human-readable connectivity table for review

**Integration:** Add call at end of `spice_to_verilog_ams()` in `complete_pipeline.py`
after step 8 (save files):
```python
if len(va_files) > 1:
    from system_assembler import assemble_system
    system_va = assemble_system(va_files, output_dir, client_id=client_id)
```

**Scope guard:** Auto-connection is heuristic. Do NOT attempt to run the equivalence
checker across all block pairs to validate connections — O(n²) simulation cost.
The `// TODO:` stubs + instantiation_list.txt is the right V1 tradeoff.

---

### P4 — Client-Aware Entry Point (Depends on P1–P3)

**New file: `client_runner.py`**

```python
def run_for_client(netlist_path: str, client_id: str,
                   output_dir: str = None,
                   use_complete_pipeline: bool = False,
                   export_testbenches: bool = True) -> dict
```

- Sets `output_dir` default to `outputs/{client_id}/{timestamp}/` for per-client isolation
- Calls `run_pipeline()` or `spice_to_verilog_ams()` with `client_id` propagated
- Returns `{va_files, system_va, testbench_dir, nrmse}`
- CLI: `python client_runner.py --client apple --netlist serdes_top.cir --complete`

---

## What NOT to Build Yet

- **Vector embeddings RAG** — unnecessary until corpus > ~50 docs per client
- **Web UI or REST API** — engineers invoke directly; add after product validation
- **Cadence Spectre testbench format** — separate feature request
- **Automatic net topology inference for system assembler** — heuristic + TODO stubs is correct V1
- **Cross-client RAG** — never; client data stays sandboxed in `clients/{client_id}/`
- **Modify SYSTEM_PROMPT directly** — compose via `_build_system_prompt()` to preserve A/B testability

---

## File Change Summary

| File | Type | Change |
|------|------|--------|
| `rag/__init__.py` | Create | Empty package |
| `rag/client_store.py` | Create | ClientStore — keyword-ranked file-system RAG |
| `system_assembler.py` | Create | assemble_system() — parse .va ports, wire blocks, emit system_top.va |
| `testbench_exporter.py` | Create | Standalone testbench export for AI pipeline path |
| `client_runner.py` | Create | Client-aware entry point CLI + Python API |
| `clients/` | Create (dir) | Per-client doc store (not Python) |
| `ai_agent.py` | Modify | Add `_build_system_prompt()`, `client_context` kwarg to generate/refine |
| `pipeline.py` | Modify | Add `client_id` to run_pipeline(), load + pass RAG context |
| `pipeline_ext/complete_pipeline.py` | Modify | Activate testbench_output_dir, add client_id param, call assemble_system() |

---

## Verification (P1–P4, already implemented)

1. **RAG:** `python -c "from rag.client_store import ClientStore; store = ClientStore('apple'); print(store.get_context())"`
2. **Testbench export:** Run `spice_to_verilog_ams()` on `bjt_amplifier.cir`, verify `testbenches/` is created
3. **System integration:** Run on two-block netlist, verify `system_top.va` has both instantiations
4. **Client runner CLI:** `python client_runner.py --help` — all options present

---

## P5 — Repository Cleanup

**Context:** The repo has accumulated ~15 stale root-level test scripts, ~14 development
investigation .md files, and 4 stray .cir netlists that should be in `examples/netlists/`.
The organized tests are in `tests/`, docs are in `docs/`. The root should contain only
core source, entry points, and one README.

### Target structure after cleanup

```
SynapticAMS/
├── README.md                     ← updated (reflects new features + client runner)
├── .gitignore                    ← add my_demo_results/
│
├── pipeline.py                   ← core AI pipeline (keep)
├── ai_agent.py                   ← LLM backends (keep)
├── ngspice_runner.py             ← simulation (keep)
├── spice_flatten.py              ← SPICE preprocessing (keep)
├── hybrid_ensemble.py            ← ensemble runner (keep — README references it)
├── oscillator_equivalence.py     ← VCO equivalence checker (keep — used by complete_pipeline)
├── client_runner.py              ← new client-aware entry point (keep)
├── system_assembler.py           ← structural scaffold (keep, repositioned)
├── testbench_exporter.py         ← testbench export (keep)
│
├── pipeline_ext/                 ← non-AI numeric fitting pipeline (unchanged)
├── equivalence_checker/          ← OSDI equivalence checking (unchanged)
├── rag/                          ← per-client RAG (new)
├── clients/                      ← per-client docs (new)
│
├── examples/
│   └── netlists/
│       ├── bjt_amplifier.cir
│       ├── nmos_dc_sweep.cir
│       ├── serdes_cml.cir
│       ├── test_netlist_simple.cir
│       ├── vco_ring5.cir
│       ├── openserdes_complete.cir   ← moved from root
│       ├── serdes_oscillating.cir    ← moved from root
│       ├── serdes_top_fixed.cir      ← moved from root
│       └── serdes_vco_only.cir       ← moved from root
│
├── tests/                        ← organized test suite (unchanged)
│   ├── test_pipeline.py
│   ├── test_pipeline_comparison.py
│   ├── test_hybrid_nmos.py
│   ├── test_serdes_full.py
│   └── test_pll_demo.py
│
├── demo/
│   ├── app.py                    ← Streamlit UI (keep)
│   ├── demo_warmstart.py         ← moved from root
│   └── demo_warmstart_validated.py ← moved from root
│
└── docs/                         ← user-facing architecture docs (keep as-is)
    ├── PIPELINE_ARCHITECTURE.md
    ├── HYBRID_ENSEMBLE_GUIDE.md
    ├── EQUIVALENCE_CHECKING_SUMMARY.md
    ├── OSCILLATOR_EQUIVALENCE_INTEGRATION.md
    ├── TRANSIENT_PARAM_EXTRACTION.md
    ├── diagram.png
    └── ngspice-45-manual.pdf
```

### Files to DELETE (stale dev artifacts — all preserved in git history)

**Root-level investigation/fix .md and .txt files (14):**
- `2D_OSDI_EQUIVALENCE_ISSUE.md`, `2D_OSDI_FIX_SUMMARY.md`
- `CLAUDE_SUGGESTION_HYBRID_FRAMEWORK.txt`
- `DC_SWEEP_VALIDATION_ROOT_CAUSE.md`
- `DEMO_QUICKSTART.md`, `DEMO_WARMSTART_README.md`
- `DYNAMIC_FITTING_IMPLEMENTATION.md`, `IMPLEMENTATION_SUMMARY.md`
- `PIPELINE_FALLBACK_GUIDE.md`, `RING_OSCILLATOR_FIX.md`
- `SERDES_CONVERGENCE_ANALYSIS.md`, `SPICE_EC_RESULTS_GUIDE.md`
- `TRANSIENT_EXTRACTION_QUICKSTART.md`, `TRANSIENT_VALIDATION_FIX.md`
- `VALIDATED_DEMO_README.md`

**Root-level legacy test scripts (15) — superseded by organized tests/:**
- `test_parser.py`, `test_ngspice_dc_sweep.py`, `test_no_timeout.py`
- `test_force_fallback.py`, `test_pipeline_fallback.py`
- `test_serdes_hybrid.py`, `test_serdes_hybrid_final.py`
- `test_openserdes_hybrid.py`, `test_serdes_fixed.py`
- `test_serdes_complete_pipeline.py`
- `test_transient_equiv_debug.py`, `test_transient_gm_gds.py`
- `test_transient_only_gain.py`, `test_amplifier_dynamic.py`
- `test_dynamic_fitting.py`, `test_vco_dynamic.py`

### Files to MOVE

| From | To |
|------|----|
| `demo_warmstart.py` | `demo/demo_warmstart.py` |
| `demo_warmstart_validated.py` | `demo/demo_warmstart_validated.py` |
| `openserdes_complete.cir` | `examples/netlists/openserdes_complete.cir` |
| `serdes_oscillating.cir` | `examples/netlists/serdes_oscillating.cir` |
| `serdes_top_fixed.cir` | `examples/netlists/serdes_top_fixed.cir` |
| `serdes_vco_only.cir` | `examples/netlists/serdes_vco_only.cir` |

### Files to UPDATE

**`.gitignore`** — add: `my_demo_results/` and `outputs/`

**`README.md`** — rewrite to reflect:
- Updated directory structure
- New entry points: `client_runner.py` (primary), `pipeline.py`, `hybrid_ensemble.py`
- New `clients/` RAG directory with onboarding instructions
- Testbench export and system_top.va outputs
- Remove references to deleted docs

---

## P5.5 — AI-Driven System Integration (Mixed-Signal)

### Problem

`system_assembler.py` does structural port-name matching. It wires `tx_out_p → tx_out_p`
when both blocks share the exact same net name. That handles the easy 40–60% of connections.

The hard part — the reason AI is necessary — is everything else:
- `CLK_16G` (analog VCO output) connects to `clk` (digital CDR input): different names, same signal
- `tx_out_p/n` (EENet differential) drives `rx_in_p/n` (Verilog `input logic`): domain crossing
- Supply rails: `VDD_IO` on the TX block may be distinct from `VDD_CORE` on the RX block
- Protocol awareness: LVDS → CMOS transition needs a comparator stub, not a direct wire
- A spec says "TX drives RX through 50Ω channel" but there is no explicit channel block in the netlist

None of these can be solved by Python name rules. They require reading intent.

---

### What NOT to pass to AI

**Don't pass raw files.** A 500-line `.va` file + a 300-line `.sv` file + a 20-page spec
is 10,000+ tokens of noise. AI performance degrades with irrelevant context. The syntax
of Verilog and Verilog-AMS is not what we want AI reasoning about — port semantics are.

---

### Two-Phase Architecture

```
Phase 1 — Structural scaffold (non-AI, already implemented)
  system_assembler.assemble_system()
  → exact-name port matching
  → emits system_top.va with // TODO: connect stubs
  → emits instantiation_list.txt

Phase 2 — AI semantic resolution (new)
  system_assembler.ai_resolve_stubs()
  → extracts structured port tables from each block (small, precise)
  → retrieves spec snippet via RAG (client docs or uploaded spec)
  → AI prompt = stub VA + port tables + spec context
  → AI fills in TODO stubs, flags domain crossings, adds rationale comments
  → returns updated system_top.va
```

Phase 2 is optional — if no AI agent is available, the stub from Phase 1 is still useful.

---

### What AI receives (structured, not raw)

The prompt is built from three distilled inputs:

**1. Port table summaries (extracted by Python, not raw source)**

```
Block: TxDiffPair  [tx_diffpair.va]
  Type: analog behavioral (Verilog-AMS)
  Outputs: tx_out_p (EENet), tx_out_n (EENet)
  Inputs:  tx_in_p (EENet), tx_in_n (EENet)
  Supply:  vdd (electrical), vss (electrical)
  Params:  gain=4.5, tau=7.96e-10, voh=1.6V, vol=1.0V
  Inferred role: differential output driver (SerDes TX)

Block: RxDecision  [rx_decision.sv — Verilog SystemVerilog]
  Type: digital RTL
  Outputs: rx_data_out [1-bit logic]
  Inputs:  rx_in_p [1-bit], rx_in_n [1-bit], clk [logic], rst_n [logic]
  Inferred role: differential input decision circuit / CDR
```

**2. The scaffold stub (already short — only the TODO lines matter)**

```verilog
// TODO: connect TxDiffPair.tx_out_p
// TODO: connect TxDiffPair.tx_out_n
// TODO: connect RxDecision.rx_in_p
// TODO: connect RxDecision.rx_in_n
// TODO: connect RxDecision.clk
```

**3. Spec context (RAG-retrieved snippet, not the full document)**

Retrieved from `clients/{client_id}/system_docs/` using block names as keywords:

```
"The TX differential pair drives the RX decision circuit through a 50Ω
stripline channel modeled as a first-order RC lowpass. CLK_16G from the
VCO feeds the digital CDR block directly."
```

---

### AI task and prompt structure

System prompt addendum (appended to `_build_system_prompt(client_context)`):

```
You are a mixed-signal integration engineer. Given a set of analog and digital
blocks with their port tables, a partially-connected top-level stub, and a
system spec excerpt, resolve every // TODO: connect annotation.

Rules:
- Match ports semantically, not just by name. A differential TX output (out_p/n)
  connects to a differential RX input even if port names differ.
- Flag domain crossings: when an analog EENet port connects to a logic port,
  add a comment: // DOMAIN CROSSING — needs level-shifter or wreal adapter
- Flag supply domain mismatches: if VDD_IO ≠ VDD_CORE, add a comment.
- If a connection is ambiguous, make the best guess and annotate:
  // INFERRED CONNECTION — verify against full spec
- Return ONLY the updated system_top.va. No prose.
```

User prompt: port tables + stub + spec snippet (typically < 800 tokens total).

---

### Handling Verilog/SV digital blocks

The existing `system_assembler._parse_module()` uses regex on Verilog-AMS syntax.
Extend it to parse `.v`/`.sv` module declarations:

```python
# .va ports:  "output electrical out_p;"  "input electrical in_p;"
# .v ports:   "output logic [7:0] data_out,"  "input clk,"
# .sv ports:  "output logic data_out,"  "input var logic [3:0] addr,"
```

Same regex approach — extract direction, width (for buses), name. Tag the block type
as `analog` (.va) or `digital` (.v/.sv) so AI knows to expect domain crossing.

For buses (`[7:0]`), extract width and include in the port table summary. AI can then
infer that an 8-bit digital bus does not directly connect to a single analog EENet port.

---

### Domain crossing rules (AI-flagged, engineer-resolved)

| From | To | Action |
|------|----|--------|
| `electrical` / `EENet` | `logic` | Insert comparator stub or `wreal` adapter |
| `logic` | `electrical` / `EENet` | Insert DAC stub or `wreal` driver |
| `wreal` | `electrical` | Direct connection (same domain, different type) |
| `electrical` | `electrical` | Direct wire |
| `logic` | `logic` | Direct wire (check widths) |

AI annotates these as `// DOMAIN CROSSING` comments. The stub is still syntactically
valid — the engineer replaces stubs with actual adapter modules before tape-out.

---

### API

```python
# system_assembler.py additions

def extract_port_table(path: Path) -> dict:
    """
    Parse a .va or .v/.sv file. Returns:
    {module_name, file_type ('analog'|'digital'), ports: [{name, direction, discipline, width}],
     params: {name: value}, inferred_role: str}
    """

def ai_resolve_stubs(scaffold_va: str,
                     port_tables: list[dict],
                     spec_context: str | None,
                     agent,
                     client_context: str | None = None) -> str:
    """
    Phase 2: AI resolves // TODO stubs.
    Builds a minimal prompt from port_tables + stub + spec_context.
    Returns updated system_top.va string.
    """

def assemble_system_full(va_and_v_files: list[Path],
                          output_dir: str,
                          system_name: str = "system_top",
                          spec_text: str | None = None,
                          agent = None,
                          client_id: str | None = None) -> Path:
    """
    Full pipeline: Phase 1 (scaffold) + optional Phase 2 (AI resolution).
    If agent is None, returns Phase 1 scaffold only.
    spec_text: raw system-level specification text (or None).
               If client_id set, spec context auto-retrieved from RAG.
    """
```

---

### Integration with client_runner.py

```python
# client_runner.py extension
result = run_for_client(
    netlist_path="serdes_top.cir",
    digital_blocks=["rx_decision.sv", "digital_cdr.sv"],  # new param
    spec_path="specs/serdes_system_spec.pdf",              # new param — text extracted
    client_id="apple",
    use_complete_pipeline=True,
)
# result["system_va"] now has AI-resolved connections, not just structural stubs
```

The spec extraction (PDF → text) can use stdlib `pdfminer` or just accept `.txt`/`.md`
— the engineer pastes the relevant section, not the whole 200-page spec.

---

### Why this is better than "just pass everything"

| Approach | Context tokens | AI accuracy | Implementation effort |
|----------|---------------|-------------|----------------------|
| Raw .va + .sv + spec | ~15,000+ | Degrades, misses intent | None (just concatenate) |
| Structured port tables + stub + RAG snippet | ~800–1,200 | High (focused task) | Medium |
| Name-matching only (current) | 0 | Fails on cross-domain | Done |

The middle row is the right tradeoff. The extraction step (port tables) is
straightforward regex — the same pattern already used in `system_assembler._parse_module()`.
The spec RAG retrieval reuses the existing `ClientStore` infrastructure (add a
`system_docs/` folder to the client directory).

---

### Implementation order

1. Extend `_parse_module()` to handle `.v`/`.sv` syntax → `extract_port_table()`
2. Add `ai_resolve_stubs()` with the integration prompt
3. Add `assemble_system_full()` that chains both phases
4. Add `system_docs/` support to `ClientStore.get_context()`
5. Extend `client_runner.py` with `digital_blocks` and `spec_path` params

---

## P5.6 — Source-Level Block Modifications for Integration

### When wiring alone is not enough

Phase 2 (AI resolving `// TODO` stubs) assumes all needed ports already exist on
every block. Sometimes they don't, or the behavioral model is wrong for the system
context. This is a separate class of problem from connection routing.

**Full taxonomy of integration mismatches:**

| Mismatch type | Can adapter solve it? | Correct action |
|---------------|-----------------------|----------------|
| Discipline-only boundary (`electrical` ↔ `EENet`) | **Yes** | Generate thin discipline-bridge adapter module |
| Analog → digital domain crossing | **Yes** | Generate ideal comparator or `wreal` adapter |
| Digital → analog domain crossing | **Yes** | Generate DAC stub or `wreal` driver adapter |
| Parameter value wrong for supply domain | **Yes** | Override at instantiation (no file change) |
| Port missing but behavior is separable | **Sometimes** | Adapter if interface-only; in-place if interior logic depends on it |
| Port fundamentally absent (e.g., single-ended model, system needs differential) | **No** | In-place modification of `.va` → re-validate NRMSE |
| Discipline wrong *inside* module (clamping uses `electrical` internally) | **No** | In-place modification → re-validate |
| Behavior fit at wrong supply voltage | **No** | Re-generate block from SPICE netlist with new VDD |

---

### Principle: adapter-first, in-place modification as last resort

**Why adapters are strongly preferred:**
- The original `.va` was validated by NRMSE against SPICE ground truth. Modifying it
  invalidates that verification — you must re-run the simulation + feedback loop.
- Adapters are non-destructive: delete and retry without touching the verified model.
- Standard EDA practice: interface adapters (level-shifters, CDC bridges) are always
  separate cells, not inline edits to the IP block they connect to.

**When in-place modification is unavoidable:**
- Port is used *inside* the analog block (e.g., `V(in_n)` referenced in analog body)
  and is absent from the module declaration — an adapter cannot add it.
- Discipline change affects clamping or internal expressions: `min(voh, max(vol, V(out)))`
  breaks if `out` becomes `EENet` but the body was written for `electrical`.
- Supply voltage change shifts VOH/VOL/gain significantly (not a simple parameter override).

---

### Adapter generation (preferred path)

AI generates a separate bridge module. The system_top.va instantiates the adapter
between the two blocks. Original source files are not touched.

**Example — discipline bridge (`electrical` → `EENet`):**
```verilog
// auto-generated: TxDiffPair_bridge.va
`include "disciplines.vams"
module TxDiffPair_EENet_bridge (out_p, out_n, in_p, in_n);
  output EENet out_p;  output EENet out_n;
  input  EENet in_p;   input  EENet in_n;
  electrical e_in_p, e_in_n, e_out_p, e_out_n;
  TxDiffPair i (.out_p(e_out_p), .out_n(e_out_n),
                .in_p(e_in_p),   .in_n(e_in_n));
  V(out_p) <+ V(e_out_p);  V(out_n) <+ V(e_out_n);
  V(e_in_p) <+ V(in_p);   V(e_in_n) <+ V(in_n);
endmodule
```

**Example — analog → digital domain crossing:**
```verilog
// auto-generated: AnalogToLogic_comparator.va
`include "disciplines.vams"
module AnalogToLogic_comparator (logic_out, in_p, in_n);
  output logic logic_out;      // Verilog-AMS mixed-signal port
  input  EENet in_p, in_n;
  real vdiff;
  analog begin
    vdiff = V(in_p) - V(in_n);
  end
  assign logic_out = (vdiff > 0.0) ? 1'b1 : 1'b0;  // ideal comparator
  // ENGINEER NOTE: replace with calibrated threshold if ISI matters
endmodule
```

**Example — parameter override (no file, no adapter — just instantiation syntax):**
```verilog
// system_top.va: parameter override at instantiation
TxDiffPair #(.voh(1.2), .vol(0.05)) i_tx (.out_p(w_tx_p), ...);
```

---

### In-place modification (last resort path)

Triggered when adapter cannot bridge the mismatch. Two sub-cases:

**Sub-case A — Port missing, in-place modification sufficient**

Example: generated VA is single-ended `module TxStage (out, in)` but system needs
differential `module TxStage (out_p, out_n, in_p, in_n)`.

AI action:
1. Read the original `.va` + the original SPICE netlist
2. Modify the port declaration and the `analog begin` body to use differential signals
3. Save original as `model.va.bak` (non-destructive)
4. **Trigger NRMSE re-validation** against the SPICE ground truth — the modification
   may have changed behavior; the original verification no longer applies

**Sub-case B — Behavioral model fit for wrong operating point**

Example: block was simulated at VDD=1.8V, extracted VOH=1.75V, VOL=0.05V. System
VDD is 1.2V — the model parameters are simply wrong, not just the interface.

AI action:
1. Flag this to the engineer: "Block `TxDiffPair` was characterized at 1.8V; system
   VDD is 1.2V. Recommend re-running the behavioral generation pipeline."
2. Optionally: re-invoke `pipeline.py` on the original SPICE netlist with updated sweep
   range to re-extract VOH/VOL/gain at 1.2V, then regenerate.
3. This is a full re-run, not an edit — treat it as a new pipeline invocation.

**AI does NOT silently edit parameters.** Changing `voh=1.8` to `voh=1.2` without
re-fitting the full transfer characteristic produces an incorrect model (gain, Vth,
and shape all shift together at a different supply). The correct action is regeneration.

---

### Re-validation trigger

Whenever any `.va` file is modified in-place during integration:

```python
# system_assembler.py: after in-place modification
from pipeline import run_pipeline
_, new_nrmse = run_pipeline(original_netlist, output_dir=block_output_dir,
                             client_id=client_id)
if new_nrmse > NRMSE_THRESHOLD:
    print(f"  WARNING: {module_name} NRMSE={new_nrmse:.4f} after modification — review manually")
```

This re-runs Step 2 (DC sweep) + Step 4 (AI generation + feedback loop) only for the
modified block. The rest of the system assembly proceeds with the re-validated model.

---

### Detection logic (how the system decides which path to take)

```python
def classify_mismatch(block_a: dict, port_a: str,
                      block_b: dict, port_b: str) -> str:
    """
    Returns one of:
      'parameter_override'   — fix at instantiation, no file change
      'adapter_discipline'   — generate discipline bridge module
      'adapter_domain'       — generate analog/digital crossing adapter
      'inplace_port'         — port missing, modify source file
      'regenerate'           — behavioral model wrong for operating point
    """
```

Rules (checked in order, first match wins):
1. Ports exist on both sides, only discipline differs → `adapter_discipline`
2. One side is `logic`/digital, other is `electrical`/`EENet` → `adapter_domain`
3. Parameter values mismatched but port exists and is exposed → `parameter_override`
4. Port completely absent from module declaration → `inplace_port`
5. Supply voltage or operating-point shift > 20% → `regenerate`

---

### Updated API

```python
# system_assembler.py

def assemble_system_full(
    va_and_v_files: list[Path],
    output_dir: str,
    system_name: str = "system_top",
    spec_text: str | None = None,
    agent = None,
    client_id: str | None = None,
    allow_inplace_modification: bool = False,  # default: safe mode
    revalidate_after_modification: bool = True,
) -> SystemAssemblyResult:
    """
    Full pipeline:
      Phase 1: structural scaffold (exact-name wiring)
      Phase 2: AI semantic resolution of TODO stubs (if agent provided)
      Phase 3: mismatch classification + adapter generation or in-place edit
               (only if allow_inplace_modification=True)

    Returns SystemAssemblyResult with:
      system_va: Path to system_top.va
      adapter_modules: list[Path] of generated adapter .va files
      modified_blocks: list[Path] of in-place-modified blocks (with .bak originals)
      revalidation_results: {module_name: nrmse} for re-validated blocks
      unresolved: list of (block, port) pairs still needing manual review
    """
```

`allow_inplace_modification` defaults to `False` — the system produces stubs and
adapter suggestions without touching verified source files unless the engineer
explicitly opts in. This is the safe default for production IP.

---

### What AI should and should not do autonomously

| Action | Autonomous OK? | Rationale |
|--------|---------------|-----------|
| Generate adapter module | **Yes** | Non-destructive, additive, engineer reviews |
| Parameter override at instantiation | **Yes** | Syntactically safe, reversible |
| Add `// DOMAIN CROSSING` comment | **Yes** | Documentation only |
| Modify port declaration of a `.va` | **Only with `allow_inplace_modification=True`** | Invalidates NRMSE verification |
| Change parameter values inside `.va` body | **Never autonomously** | Must regenerate from SPICE |
| Delete or rename a port | **Never autonomously** | Breaking change to verified model |

---

## P5.6b — Fix Dynamic Model NRMSE Validation (Prerequisite for P5.7)

### The current gap

The pipeline generates `laplace_nd` models for any circuit where the AC sweep
returns bandwidth data. These are the most important models for SerDes and filter
blocks — exactly the circuits SynapticAMS is designed for. Yet they have **zero
numerical validation** today.

**Why:** two code paths work against each other:

```
evaluate_va_code() in ai_agent.py:
  Has DC substitution — replaces laplace_nd(signal, {num}, {den}) → (signal)
  So it CAN compute a DC NRMSE for dynamic models (captures VOH, VOL, Vth, gain)
  but loses all frequency-response information.

_is_dynamic_model() in pipeline.py (line ~985):
  Detects laplace_nd → prints "Dynamic model detected — NRMSE validation skipped"
  → returns WITHOUT calling evaluate_va_code() at all
```

Result: for any `laplace_nd` model, NRMSE is never computed, the refinement loop
never runs, and the model is saved with no confidence measure.

Additionally, `ac_metrics` (frequencies + magnitude_db + phase from ngspice AC sweep)
is collected in Step 3 but **only passed to the AI prompt** — it is never used to
validate the generated model's frequency response.

---

### Fix: two-layer dynamic model validation

**Layer A — DC NRMSE (static behavior of dynamic model)**

Remove the `_is_dynamic_model()` early return. Let `evaluate_va_code()` run on
`laplace_nd` models using its existing DC substitution. This gives a valid NRMSE
for VOH, VOL, Vth, and gain — the static transfer characteristic at s=0.

This is meaningful because a wrong gain or wrong clamp level will show up as high
DC NRMSE even though the frequency response is being ignored. The refinement loop
can correct these static errors.

```python
# pipeline.py: REMOVE this block (lines ~985-991)
if _is_dynamic_model(va_code):
    print("      Dynamic model detected (laplace/ddt) — NRMSE validation skipped.")
# INSTEAD: fall through to the existing evaluate_va_code() loop
# evaluate_va_code() already handles laplace_nd via DC substitution
```

**Layer B — Frequency-domain NRMSE (dynamic behavior)**

New function `compute_bode_nrmse(va_code, ac_metrics)` in `ai_agent.py`:

1. Parse the `laplace_nd` coefficients from the VA code using regex:
   `laplace_nd(signal, {num_coeffs}, {den_coeffs})` → extract `[n0, n1, ...]` and
   `[d0, d1, ...]` arrays

2. Build a scipy transfer function:
   ```python
   from scipy import signal as sp
   sys = sp.TransferFunction(num_coeffs, den_coeffs)
   ```

3. Evaluate at the same frequencies ngspice used:
   ```python
   _, mag_model = sp.bode(sys, w=2*np.pi*ac_metrics['frequencies'])
   # mag_model is dB magnitude of H(jω)
   ```

4. Compare against ngspice AC sweep:
   ```python
   mag_golden = ac_metrics['magnitude_db']  # from ngspice
   bode_nrmse = np.sqrt(np.mean((mag_model - mag_golden)**2)) / np.ptp(mag_golden)
   ```

5. If `bode_nrmse > threshold`: feed both the DC NRMSE and Bode NRMSE into the
   refinement prompt so AI knows the frequency response is wrong, not just the
   DC gain.

**What this covers:**

| Model type | DC NRMSE | Bode NRMSE |
|------------|----------|------------|
| Static (`V(out) <+ expr`) | Yes (existing) | N/A |
| `laplace_nd` first-order | Yes (DC substitution) | Yes (scipy) |
| `laplace_nd` higher-order | Yes | Yes |
| `ddt` / `idt` / `idtmod` | No (not a transfer function) | No |

`ddt`/`idt` models (ring VCO phase integration) cannot be validated with DC or
frequency-domain checks — those need transient simulation. Flag with a warning;
they are out of scope for automated checking.

---

### Where OpenVAF/OSDI fits (and does NOT fit)

**OpenVAF compile** — still used for syntax checking. `openvaf model.va` catches
port direction errors, undefined variables, type mismatches. This is independent
of NRMSE and should run on every generated model.

**ngspice OSDI** — confirmed NOT suitable for behavioral models. ngspice's OSDI
interface targets transistor compact models (BSIM, PSP, VBIC). A behavioral
`V(out) <+ f(V(in))` module is not a compact model — it has no Jacobian
contributions in the sense OSDI expects. This was established in Test 4 of the
previous test run.

**What this means:** the pipeline's numerical validation path is and will remain:
```
ngspice DC/AC sweep → golden truth
evaluate_va_code() + compute_bode_nrmse() → behavioral model truth
compare → NRMSE (two numbers: DC + Bode)
```
There is no path through OpenVAF/OSDI for numerical evaluation of behavioral models.

---

### Refinement prompt update for dynamic models

`_build_refine_prompt()` in `ai_agent.py` currently only reports DC NRMSE.
Extend to report both metrics when `ac_metrics` is available:

```
Current model NRMSE:
  DC (static transfer curve):  0.18  ← gain or clamp is wrong
  Bode (frequency response):   0.34  ← tau / pole frequency is wrong

The DC gain is too high (model gain ≈ 8.2, target ≈ 5.1).
The -3dB frequency is 3.1 GHz in the model vs 1.4 GHz in ngspice.
Adjust gain parameter and tau to match both metrics.
```

This replaces the current "NRMSE=X, try again" feedback with specific, actionable
numbers for both the static and dynamic aspects of the model.

---

### Modified files

| File | Change |
|------|--------|
| `pipeline.py` | Remove `_is_dynamic_model()` early return; add `compute_bode_nrmse()` call after DC NRMSE when `ac_metrics` available |
| `ai_agent.py` | Add `compute_bode_nrmse(va_code, ac_metrics) → float`; update `_build_refine_prompt()` to accept and display both NRMSEs |

---

## P5.7 — System-Level Equivalence Checking and Testbench Integration

### Why block-level NRMSE is not enough

Block NRMSE proves each behavioral model is correct in isolation with no load.
When blocks are assembled into a system, three new failure modes appear that
no per-block check can catch:

1. **Loading effects** — block A was characterized with a 1MΩ load; in the system
   it drives block B which has 50Ω input impedance. The transfer function shifts.
2. **Adapter errors** — AI-generated discipline bridges and domain-crossing adapters
   have never been verified against any simulation ground truth. They are only
   structurally correct, not behaviorally validated.
3. **Global feedback** — a feedback path that spans multiple blocks creates dynamics
   (oscillation, settling time, phase margin) invisible to any single-block DC sweep.

The system also introduces a new problem for testbench generation: block-level
testbenches each probe one output node in isolation. A system testbench must apply
realistic stimulus at system inputs and measure multiple output nodes simultaneously
— a fundamentally different document.

---

### Four layers of checking required

| Layer | What it checks | Can we automate? | Tool needed |
|-------|---------------|-----------------|-------------|
| 1 — Block NRMSE | Each behavioral model vs SPICE block ground truth | **Yes (P5.6b fix needed)** | ngspice + Python eval (DC) + scipy (Bode) |
| 2 — Adapter correctness | Discipline bridges, domain-crossing adapters | **Yes — static analysis** | Python only |
| 3 — SPICE node trajectory | System-level per-node DC+Bode vs original netlist | **Yes — ngspice + scipy** | NgspiceRunner + compute_bode_nrmse() |
| 4 — Behavioral system sim | Simulate `system_top.va` as a whole with feedback | **No — needs EDA license** | Cadence Spectre / HSPICE |

**Important:** OpenVAF compile is used for **syntax checking only** at every layer.
It does not contribute to numerical evaluation. ngspice OSDI is confirmed
non-functional for behavioral `V(out) <+` models and is not used in any layer.

Our pipeline must own Layers 1–3 fully. Layer 4 is the engineer's responsibility;
our job is to generate the testbench they need to run it.

---

### Layer 2 — Adapter correctness (static, no simulation)

Adapter modules fall into two categories with deterministic correctness rules:

**Discipline bridge** (`electrical` ↔ `EENet` or similar):
Correct iff: `V(out) <+ V(in)` with no gain, phase shift, or filtering.
Check: regex scan of adapter body — any expression other than `V(out_x) <+ V(in_x)`
is a red flag. This is a template-generated module; the template is verified once.

**Domain-crossing adapter** (analog comparator, DAC stub):
Correct by construction for ideal models (zero threshold error, infinite bandwidth).
Flag with `// IDEAL MODEL — replace before tapeout` comment.
For non-ideal adapters (finite bandwidth, calibrated threshold): requires Layer 3.

**Parameter override at instantiation:**
Check: `voh > vol`, `tau > 0`, `gain > 0`. Python static analysis, no simulation.

**What triggers a Layer 2 failure:**
- Adapter body contains an unexpected expression (AI added gain accidentally)
- Parameter override produces physically impossible values
- Discipline bridge has directionality error (output wired to output)
These are caught before any simulation is run.

---

### Layer 3 — SPICE node trajectory comparison (automated, ngspice)

This is the closest we can get to full system verification without a Verilog-AMS
simulator. The original full SPICE netlist is the ground truth for the system.
Critically, Layer 3 must use the same two-layer validation approach defined in P5.6b:
DC NRMSE for static models, Bode NRMSE for dynamic models. **It does NOT use
OpenVAF/ngspice-OSDI for numerical evaluation** — that path is confirmed non-functional
for behavioral models (see P5.6b rationale).

**Algorithm (two tracks, per block):**

```
For each block in the system, determine its model type:

Track A — Static blocks (no laplace_nd / ddt):
  1. Run NgspiceRunner.dc_sweep() on full SPICE netlist
     → extract V at each internal node over DC sweep range
  2. For each static block's output node:
     a. Evaluate block VA model via evaluate_va_code() (Python, DC subst.)
     b. DC NRMSE: golden_node_voltage vs behavioral_block_output
  3. Report per-node DC NRMSE across signal chain

Track B — Dynamic blocks (laplace_nd, first-order and higher):
  1. Run NgspiceRunner.ac_sweep() on full SPICE netlist
     → extract magnitude_db + phase at each internal node over frequency range
  2. For each dynamic block's output node:
     a. Parse laplace_nd coefficients from VA code (regex, same as P5.6b)
     b. Compute scipy Bode response at SPICE sweep frequencies
     c. Bode NRMSE: golden_node_magnitude_db vs behavioral_bode_db
  3. Report per-node Bode NRMSE across signal chain

Both tracks:
  4. Flag any node with NRMSE > threshold → AI diagnoses likely cause
  5. NOTE: ddt/idt/idtmod (VCO phase models) cannot be validated at Layer 3
     — they are transient-only and require Layer 4 (EDA testbench)
```

**What Layer 3 catches that block-level NRMSE misses:**
- **Loading effects** — SPICE shows block A's output drooping under block B's load;
  the block-level model was fit with no load → high DC NRMSE at the boundary node
- **Accumulated gain error** — four blocks each at 4% DC NRMSE can compose to 15%
  at the system output; Layer 3 catches this explicitly at each stage
- **Pole frequency error** — block-level Bode NRMSE may pass for a single block but
  two cascaded lowpass stages produce a different cutoff; Layer 3 catches this

**What Layer 3 still cannot catch:**
- Feedback-path dynamics (requires full system simulation — Layer 4)
- Common-mode behavior in differential pairs (DC sweep is single-ended)
- Transient startup / settling (DC sweep is steady-state only)
- VCO / ring oscillator frequency accuracy (transient-only, no DC/AC representation)

---

### Layer 4 — System testbench for engineer's EDA environment

We cannot run Cadence Spectre in the pipeline. But we can generate the testbench
the engineer needs to run Layer 4 themselves.

**Testbench generation philosophy:** one testbench document that contains everything
the engineer needs — golden reference waveforms embedded as comments, stimulus
derived from the SPICE simulation, and probe points at every block boundary.

**System testbench structure:**

```
output_dir/
  testbenches/
    system/
      system_testbench.scs        ← Cadence Spectre format (primary)
      system_testbench.sp         ← ngspice/HSPICE format (secondary)
      golden/
        spice_node_trajectories.npz   ← pre-run by our pipeline from full SPICE
        spice_node_trajectories.csv   ← human-readable version
      run_in_spectre.sh           ← convenience script with Spectre invocation
      compare_results.py          ← script: load Spectre output + compute system NRMSE
```

**What `system_testbench.scs` contains:**
1. `include` directives for every `.va` and `.sv` file in the system
2. Top-level `system_top` instantiation with stimulus sources at system inputs
3. Probe statements at every internal node (block boundaries)
4. Transient analysis covering the system's operating bandwidth
5. Golden reference comments: `// SPICE golden: V(tx_out_p) ∈ [1.0, 1.6] V`

**AI's role in testbench authorship:**
AI writes the stimulus section. Deciding what stimulus to apply to a system is
non-trivial — for a SerDes TX→RX chain, the right stimulus is a PRBS pattern at
the data rate, not a DC sweep. The AI reads the block types (from port tables +
inferred roles) and the spec snippet to choose the right stimulus waveform.

```
Prompt to AI for testbench stimulus:
  "System contains: TxDiffPair (SerDes TX, BW≈2GHz), 50Ω channel RC model,
   RxDecision (differential CDR). Generate a Spectre transient stimulus:
   PRBS-7 at 10Gbps applied to tx_in_p/n. Sweep for 20 UI."
```

This is a natural extension of the same AI prompt infrastructure already used for
VA generation — same `_build_system_prompt(client_context)`, different task.

---

### System NRMSE and AI diagnosis

Once the engineer runs the system testbench and gives us the output CSV:

```python
# compare_results.py (auto-generated, runs in engineer's env or ours)
from system_equivalence import compare_system_output

results = compare_system_output(
    golden_path="testbenches/system/golden/spice_node_trajectories.npz",
    simulated_path="spectre_output/system_top_results.csv",
)
# results: {node_name: nrmse, ...}, worst_node, failure_summary
```

If system NRMSE > threshold, AI diagnosis prompt:

```
Block-level NRMSE: TxDiffPair=0.02, RxDecision=0.03  (both PASS)
System NRMSE at tx_out_p: 0.18  (FAIL)
System NRMSE at rx_data_out: 0.31  (FAIL)

Block NRMSEs pass but system fails at the TX output node.
Likely causes: (1) loading effect — TxDiffPair was characterized with no
load but drives 50Ω in system; (2) adapter gain error — discipline bridge
may have introduced unintended attenuation; (3) DC operating point shift
when blocks are connected.
Suggested action: re-characterize TxDiffPair with 50Ω termination load
in the ngspice DC sweep.
```

AI can reason about this because it knows:
- Which block drives the failing node
- What the block's characterization conditions were (from the original SPICE sweep params)
- What the system connection looks like (from the port tables and system_top.va)

This is the "loss diagnosis" use case from the AI insertion points table (point #4),
extended to the system level.

---

### Revised pipeline flow with full checking

```
SPICE netlist(s) + optional digital .v/.sv + optional spec
  │
  ▼  [Phase 1 — Block generation, already implemented]
  per-block .va files + block-level NRMSE (Layer 1) ✓
  │
  ▼  [Phase 2 — System assembly + AI resolution, P5.5]
  system_top.va + adapter_modules/
  │
  ▼  [Phase 3 — Adapter static verification, Layer 2]
  adapter_correctness_report.txt  (pass/fail per adapter)
  │
  ▼  [Phase 4 — SPICE node trajectory comparison, Layer 3]
  system_node_nrmse_report.txt  (per-node NRMSE, AI diagnosis if fail)
  │
  ▼  [Phase 5 — System testbench generation]
  testbenches/system/system_testbench.scs   ← engineer takes to Cadence
  testbenches/system/golden/               ← golden reference pre-computed
  testbenches/system/compare_results.py    ← comparison script
  │
  ▼  [Phase 6 — Optional: engineer returns system sim output]
  system_nrmse_per_node.json + AI diagnosis
```

---

### New module: `system_equivalence.py`

Separate from `system_assembler.py` — assembly and checking are distinct concerns.

```python
# system_equivalence.py

def check_adapter_correctness(adapter_va_path: Path) -> dict:
    """Layer 2: static analysis of adapter module. Returns {passed, issues}."""

def compare_spice_trajectories(netlist_text: str,
                                block_models: dict[str, str],
                                info_dict: dict[str, dict],
                                sweep_params: dict) -> dict:
    """
    Layer 3: run full SPICE netlist, evaluate each block's VA model at
    each internal node, compute per-node NRMSE.
    block_models: {node_name: va_code_string}
    Returns {node_name: nrmse, worst_node, passed}
    """

def generate_system_testbench(system_top_va: Path,
                               block_port_tables: list[dict],
                               golden_npz: Path,
                               output_dir: str,
                               agent=None,
                               client_context: str | None = None) -> Path:
    """
    Generate system_testbench.scs + .sp + compare_results.py.
    If agent provided: AI writes the stimulus section.
    Returns path to testbenches/system/ directory.
    """

def ai_diagnose_system_failure(node_nrmse: dict,
                                block_nrmse: dict,
                                port_tables: list[dict],
                                system_top_va: str,
                                agent) -> str:
    """
    AI root-cause analysis when system NRMSE > threshold but block NRMSEs pass.
    Returns diagnostic string with likely causes and suggested actions.
    """
```

---

### Integration with client_runner.py

```python
result = run_for_client(
    netlist_path="serdes_top.cir",
    digital_blocks=["rx_decision.sv"],
    spec_path="specs/serdes_spec.txt",
    client_id="apple",
    run_system_equivalence=True,   # new: triggers Layers 2 + 3 + testbench gen
)
# result now includes:
#   "adapter_report":     dict — Layer 2 pass/fail
#   "system_node_nrmse":  dict — Layer 3 per-node NRMSE
#   "system_testbench":   Path — testbenches/system/ for engineer
#   "ai_diagnosis":       str  — if any Layer 3 node fails
```

---

### What requires EDA tools vs what we own

| Check | Who runs it | What it produces |
|-------|-------------|-----------------|
| Block NRMSE | Our pipeline (ngspice + Python) | Per-block pass/fail |
| Adapter static check | Our pipeline (Python only) | Correctness report |
| SPICE node trajectory | Our pipeline (NgspiceRunner) | Per-node NRMSE across signal chain |
| Full system VA sim | **Engineer (Cadence/Spectre)** | System waveforms |
| System NRMSE (post sim) | Our pipeline (compare_results.py) | System-level pass/fail + AI diagnosis |

The boundary is clear: we provide the golden reference and the comparison script;
the engineer provides the EDA simulation. They bring the result back and we compute
the final system-level verdict.
