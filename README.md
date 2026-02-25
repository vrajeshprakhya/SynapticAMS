# SynapticAMS

Converts a SPICE netlist into a Verilog-AMS behavioral model using an AI agent (Claude or local Ollama) with a simulation-driven feedback loop.

```
SPICE netlist
    │
    ├─[1] Parse netlist          → find signal source, output node, VDD
    ├─[2] Run ngspice DC sweep   → golden-truth I/O data
    ├─[3] AI generates code      → Verilog-AMS from netlist + data
    │       ↕  feedback loop (up to 3×): evaluate NRMSE → refine if > 5%
    └─[4] Save .va file
```

---

## How it works

The AI agent (Claude or Ollama) receives:
1. The raw SPICE netlist
2. A table of DC simulation data from ngspice (input voltage → output voltage)

It generates Verilog-AMS code, which is evaluated against the ngspice data. If the normalized RMS error (NRMSE) exceeds 5%, the agent is given the worst-case error points and asked to refine. This repeats up to **3 iterations**.

No circuit graph analysis, no transfer function fitting, no intermediate representation — just the netlist, the data, and the LLM.

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
├── pipeline.py          # Entry point — orchestrates the full 4-step pipeline
├── ai_agent.py          # AI backends (Claude / Ollama), prompts, NRMSE, evaluator
├── ngspice_runner.py    # Runs ngspice, parses DC sweep output
│
├── tests/
│   └── test_pipeline.py # Test suite (Groups A–E)
│
└── examples/
    └── netlists/        # Sample SPICE netlists
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
| A | Unit: parse_netlist, NRMSE, evaluator, clean_code | Nothing |
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
