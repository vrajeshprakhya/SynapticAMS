# SynapticAMS

Converts a SPICE netlist into a Verilog-AMS behavioral model using an AI agent (Claude or local Ollama) with a simulation-driven feedback loop.

```
SPICE netlist
    │
    ├─[1] Parse netlist          → find signal source, output node, VDD
    ├─[2] Run ngspice DC sweep   → golden-truth I/O data + DC metrics
    ├─[3] Run ngspice AC sweep   → Bode plot, -3dB bandwidth
    ├─[4] AI generates code      → Verilog-AMS from netlist + DC/AC data
    │       ↕  feedback loop (up to 3×): evaluate NRMSE → refine if > 5%
    └─[5] Save .va file
```

---

## How it works

The AI agent (Claude or Ollama) receives:
1. The raw SPICE netlist
2. A table of DC simulation data from ngspice (input voltage → output voltage)
3. Extracted DC metrics: VOH, VOL, threshold voltage, peak gain
4. AC frequency response: Bode data and -3dB bandwidth

It generates Verilog-AMS code, which is evaluated against the ngspice data. If the normalized RMS error (NRMSE) exceeds 5%, the agent is given the worst-case error points and asked to refine. This repeats up to **3 iterations**.

For circuits with bandwidth data, the AI generates a **dynamic `laplace_nd` model** (first-order lowpass) rather than a static expression. The NRMSE evaluator handles these models by substituting `laplace_nd(expr, ...)` → `expr` at DC.

---

## Hybrid Ensemble Pipeline

`hybrid_ensemble.py` runs two independent pipelines in parallel and returns the winner by NRMSE:

| Pipeline | Description |
|----------|-------------|
| **AI pipeline** | LLM-generated Verilog-AMS via `pipeline.py` |
| **Programmatic pipeline** | Small-signal parameter extraction + graph-based model via `pipeline_ext/` |

The winner is selected by simulating both models on a test DC sweep and comparing NRMSE against the ngspice golden truth.

```python
from hybrid_ensemble import ensemble_pipeline

result = ensemble_pipeline(netlist, output_dir='./output')
print(result['winner'])       # 'ai' or 'programmatic'
print(result['ai_nrmse'])     # e.g. 0.0187
print(result['va_code'])      # winning Verilog-AMS
```

---

## Demo: CML SerDes Analog Front-End

`examples/netlists/serdes_cml.cir` is a DC-sweepable 1.8V NMOS CML data path:

```
TX CML Driver (NMOS, 800Ω load, 500µA tail)
    → PCB Channel (5Ω + 200fF per side, 5cm trace)
        → RX Amplifier (NMOS, 1600Ω load, 500µA tail)
```

**Measured characteristics:**
- VOL = 1.0V, VOH = 1.8V
- Gain ≈ 5–10 V/V
- -3dB BW ≈ 200 MHz (models ~500 Mbps link)

**Generated Verilog-AMS (AI pipeline, NRMSE ≈ 1.9%):**
```verilog
module RX_AMPLIFIER (out, in);
  electrical out, in;
  parameter real voh = 1.8;
  parameter real vol = 1.0;
  parameter real vth = 0.9;
  parameter real gain = 5.07;
  parameter real tau = 7.96e-10;
  analog begin
    V(out) <+ min(voh, max(vol, vmid + gain * laplace_nd(V(in) - vth, {1.0}, {1.0, tau})));
  end
endmodule
```

**Scope note:** `serdes_cml.cir` is the analog data-path sub-block of a SerDes
(TX driver + channel + RX amplifier). It does not include CDR, PLL, serializer,
or deserializer logic. It is the DC-sweepable portion of the signal path — the
sub-block this pipeline is designed to translate.

```bash
python test_serdes_full.py
```

---

## Prerequisites

- Python 3.10+
- [ngspice](https://ngspice.sourceforge.io/) on your PATH
- One of:
  - **Free / local**: [Ollama](https://ollama.com/) with a code model
  - **Paid / cloud**: Anthropic API key

```bash
# Install Python dependencies
python -m venv .venv && source .venv/bin/activate
pip install numpy anthropic

# macOS: install ngspice and Ollama
brew install ngspice
brew install ollama && ollama serve &
ollama pull qwen2.5-coder:7b
```

---

## Quick start

```python
from pipeline import run_pipeline

netlist = """
* Common-source NMOS amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8
Vin vin 0 DC 0
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

va_path, nrmse = run_pipeline(netlist, output_dir="output/")
print(f"Generated: {va_path}")
print(f"NRMSE: {nrmse:.4f}" if nrmse else "NRMSE: N/A (no sim data)")
```

Or run directly:

```bash
source .venv/bin/activate
python pipeline.py
```

---

## Project structure

```
SynapticAMS/
│
├── pipeline.py              # Entry point — orchestrates the 5-step pipeline
├── ai_agent.py              # AI backends (Claude / Ollama), prompts, NRMSE, evaluator
├── ngspice_runner.py        # Runs ngspice, parses DC/AC/transient sweep output
├── spice_flatten.py         # SPICE 3F5 flattener (.SUBCKT / X instances)
├── hybrid_ensemble.py       # Parallel AI + programmatic pipelines, NRMSE winner selection
│
├── pipeline_ext/            # Programmatic pipeline (graph analysis, parameter fitting)
│   ├── complete_pipeline.py
│   ├── circuit_analyzer.py
│   ├── graph_builder.py
│   ├── simulation_planner.py
│   ├── fit_transfer_function.py
│   └── verilog_ams_generator.py
│
├── equivalence_checker/     # OSDI equivalence checking + independence detection
│
├── tests/
│   └── test_pipeline.py     # Test suite (Groups A–E, 56 tests)
│
└── examples/
    └── netlists/
        ├── serdes_cml.cir   # CML SerDes data path (TX→channel→RX, DC-sweepable)
        └── ...
```

---

## Running tests

```bash
source .venv/bin/activate

# Fast (no external tools needed — ~2s)
python tests/test_pipeline.py --skip-live

# Full suite (requires ngspice + Ollama)
python tests/test_pipeline.py

# Single group
python tests/test_pipeline.py --group A
python tests/test_pipeline.py --group E
```

| Group | Tests | Requires |
|-------|-------|----------|
| A | Unit: parse_netlist, NRMSE, evaluator, clean_code, spice_flatten, ngspice | Nothing |
| B | Feedback loop logic (AI + ngspice mocked) | Nothing |
| C | Live Ollama: generates real Verilog-AMS | `ollama serve` + model |
| D | Live ngspice: real DC sweep | ngspice on PATH |
| E | Full end-to-end: SPICE → ngspice → AI → .va | Both |

---

## AI backend

| Backend | How to activate |
|---------|----------------|
| **Ollama (free, local)** | Run `ollama serve` — auto-detected |
| **Claude (Anthropic)** | `export ANTHROPIC_API_KEY=sk-ant-...` |

Claude takes priority if the API key is set. To override:

```python
run_pipeline(netlist, provider="ollama", ai_model="qwen2.5-coder:7b")
```

**Recommendation:** Use Claude for best results. `qwen2.5-coder:7b` produces working
models but occasionally generates syntax errors that `clean_code()` patches automatically.

---

## Verilog-AMS model types

The AI chooses between two model forms based on available data:

| Circuit type | Model form | Example |
|-------------|-----------|---------|
| Static (no BW data) | Direct expression | `V(out) <+ min(voh, max(vol, gain*(V(in)-vth) + vmid));` |
| Dynamic (with BW) | `laplace_nd` lowpass | `V(out) <+ min(voh, max(vol, vmid + gain * laplace_nd(V(in)-vth, {1.0}, {1.0, tau})));` |

The `tau` parameter is derived from the -3dB bandwidth: `tau = 1 / (2π × BW)`.
