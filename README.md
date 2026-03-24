# SynapticAMS

Converts transistor-level SPICE netlists into Verilog-AMS behavioral models automatically.

Mixed-signal engineers spend 1–2 days per block writing behavioral models by hand. SynapticAMS does it in under a minute by simulating the circuit in ngspice, extracting its transfer characteristics, and generating a verified Verilog-AMS model via LLM with NRMSE feedback.

---

## Quick start

```bash
# Install dependencies
pip install numpy anthropic   # or: pip install numpy  (Ollama backend, free)

# Set AI backend (pick one)
export ANTHROPIC_API_KEY="sk-ant-..."          # Claude (recommended)
ollama serve && ollama pull qwen2.5-coder:7b   # Ollama (free, local)

# Run on the CML SerDes example
python pipeline.py examples/netlists/serdes_cml.cir

# Run on the ring VCO example
python pipeline.py --vco examples/netlists/vco_ring5.cir
```

**Requires:** `ngspice` on PATH — `brew install ngspice` (macOS) or `apt install ngspice` (Linux).

---

## What it does

```
SPICE netlist (.cir)
       │
       ▼  ngspice DC sweep + AC sweep
  Transfer characteristic + Bode data
       │
       ▼  LLM (Claude or Ollama)
  Verilog-AMS source (.va)
       │
       ▼  NRMSE validation loop (up to 3 refinement iterations)
  Verified behavioral model  [NRMSE < 5%]
```

For **ring VCOs**, the pipeline uses transient analysis instead:

```
SPICE netlist (.cir)
       │
       ▼  ngspice .TRAN × N control-voltage bias points
  (Vctrl, f_osc) frequency table
       │
       ▼  linear Kvco fit (no LLM needed)
  Verilog-AMS idtmod model
```

---

## CLI reference

```bash
# DC + AC pipeline  (amplifiers, filters, data-path circuits)
python pipeline.py <netlist.cir>

# VCO pipeline  (ring oscillators — generates idtmod Verilog-AMS)
python pipeline.py --vco <netlist.cir>

# Hybrid ensemble  (AI vs programmatic, returns best NRMSE)
python hybrid_ensemble.py

# Tests
python tests/test_pipeline.py --skip-live   # 56 unit tests, ~2s, no external deps
python tests/test_pipeline.py               # full suite (needs ngspice + AI backend)
python tests/test_serdes_full.py            # CML SerDes end-to-end demo
python tests/test_pll_demo.py               # VCO / PLL end-to-end demo
```

Output saves to `<netlist_stem>_output/model.va` alongside a `characterization.png` plot.

---

## Demo UI

A Streamlit UI is included for presentations. **This is not the production interface** — engineers use the CLI.

```bash
pip install streamlit matplotlib
streamlit run demo/app.py
```

---

## Examples

| Netlist | Circuit | Pipeline | Generated model |
|---------|---------|----------|-----------------|
| `examples/netlists/serdes_cml.cir` | NMOS CML TX→channel→RX, 1.8V | DC + AC | `laplace_nd` (NRMSE ≈ 1.9%) |
| `examples/netlists/vco_ring5.cir` | 5-stage current-starved ring VCO | TRAN | `idtmod` (Kvco ≈ 335 MHz/V) |
| `examples/netlists/bjt_amplifier.cir` | NPN common-emitter, DC sweep | DC | saturation model |
| `examples/netlists/nmos_dc_sweep.cir` | NMOS common-source | DC | polynomial / piecewise |

---

## Architecture

```
pipeline.py          — main CLI: run_pipeline(), run_vco_pipeline()
ai_agent.py          — LLM backends (Claude, Ollama), prompts, NRMSE evaluator
ngspice_runner.py    — dc_sweep(), ac_sweep(), tran_sweep(), extract_ac_params()
spice_flatten.py     — SPICE 3F5 flattener (.SUBCKT / X instances)

hybrid_ensemble.py           — optional: AI vs programmatic parallel comparison
oscillator_equivalence.py    — optional: frequency-domain VCO equivalence checking
equivalence_checker/         — optional: OSDI equivalence checking package
pipeline_ext/                — optional: graph-based programmatic pipeline
demo/app.py                  — Streamlit demo UI (not production)
```

### DC/AC pipeline — 5 steps

1. `parse_netlist(text)` — finds signal source, output node, VDD, DC sweep range
2. `NgspiceRunner.dc_sweep()` — returns `{source: x_array, node: y_array}`
3. `NgspiceRunner.ac_sweep()` — returns Bode magnitude + phase
4. `generate(agent, ...)` — LLM generates Verilog-AMS from netlist + simulation data
5. NRMSE loop — `evaluate_va_code()` + `compute_nrmse()` → `refine()` if NRMSE > 5%

### VCO pipeline — 3 steps

1. `vco_tran_sweep()` — `.TRAN` at N Vctrl values, rising-edge frequency extraction
2. `_fit_vco_kvco()` — linear regression → Kvco, f_ref, R²
3. `generate_vco_va()` — deterministic template using `idtmod`

---

## AI backends

| Backend | Setup |
|---------|-------|
| Claude Opus 4.6 (recommended) | `export ANTHROPIC_API_KEY=sk-ant-...` |
| qwen2.5-coder:7b via Ollama (free) | `ollama serve && ollama pull qwen2.5-coder:7b` |

Claude produces correct Verilog-AMS syntax on the first attempt. The Ollama path uses few-shot examples and a pre-filled parameter skeleton to compensate for smaller model capacity.

---

## SerDes coverage

```
TX CML driver  ──►  PCB channel  ──►  RX CML amplifier  ──►  VCO / PLL CDR
   serdes_cml.cir (DC + AC pipeline)       vco_ring5.cir (TRAN pipeline)
   laplace_nd model, NRMSE ≈ 1.9%          idtmod model, Kvco ≈ 335 MHz/V
```

Out of scope (requires PSS analysis or purely digital implementation):
PFD, charge pump, CDR loop dynamics, serializer/deserializer.

---

## Dependencies

| Package | Required for |
|---------|-------------|
| `numpy` | Core — always required |
| `ngspice` (system) | All simulations |
| `anthropic` | Claude backend |
| Ollama running locally | Ollama backend |
| `matplotlib` | Characterization plots |
| `scipy` | Oscillator equivalence checking |
| `networkx` | Graph-based programmatic pipeline |
| `streamlit` | Demo UI only |
