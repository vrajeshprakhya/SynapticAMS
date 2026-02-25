#!/usr/bin/env python3
"""
SynapticAMS: SPICE netlist → Verilog-AMS behavioral model via AI

Pipeline:
  1. Parse netlist  → find signal source, output node, supply voltage
  2. Run ngspice    → DC sweep golden-truth I/O data
  3. AI generates   → Verilog-AMS from netlist + simulation data
  4. Evaluate       → NRMSE vs SPICE ground truth
  5. Refine         → feedback loop (up to MAX_ITERATIONS)
  6. Save           → .va file

Requires: ngspice on PATH, and one of:
  - ANTHROPIC_API_KEY set  (uses Claude)
  - Ollama running locally (ollama serve && ollama pull qwen2.5-coder:7b)
"""

import re
from pathlib import Path
from ngspice_runner import NgspiceRunner, NgspiceError
from ai_agent import create_agent, generate, refine, compute_nrmse, evaluate_va_code

MAX_ITERATIONS  = 3
NRMSE_THRESHOLD = 0.05


# ── Netlist parsing ────────────────────────────────────────────────────

def parse_netlist(text):
    """
    Extract simulation parameters from a SPICE netlist.

    Returns dict with:
        signal_source  — voltage source name to sweep  (e.g. "Vin")
        output_node    — net to observe                (e.g. "vout")
        vdd            — supply voltage in volts
    """
    voltage_sources = []   # (name, plus_node, voltage)
    transistors     = []   # {"drain": ..., "gate": ...}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("*", ".")):
            continue
        tokens = line.split()
        name  = tokens[0]
        dtype = name[0].upper()

        if dtype == "V" and len(tokens) >= 3:
            m = re.search(r"DC\s+([\d.eE+-]+)", line, re.I)
            voltage = float(m.group(1)) if m else 0.0
            voltage_sources.append((name, tokens[1].lower(), voltage))

        elif dtype == "M" and len(tokens) >= 5:   # MOSFET: M D G S B model
            transistors.append({"drain": tokens[1].lower(),
                                 "gate":  tokens[2].lower()})

        elif dtype == "Q" and len(tokens) >= 4:   # BJT: Q C B E model
            transistors.append({"drain": tokens[1].lower(),
                                 "gate":  tokens[2].lower()})

    if not voltage_sources:
        raise ValueError("No voltage sources found in netlist")

    voltage_sources.sort(key=lambda v: v[2])     # ascending by voltage
    signal_src  = voltage_sources[0]             # lowest V  → signal input
    supply_src  = voltage_sources[-1]            # highest V → supply

    signal_source = signal_src[0]               # e.g. "Vin"
    supply_node   = supply_src[1]               # e.g. "vdd"
    vdd           = supply_src[2] if supply_src[2] > 0.5 else 1.8

    # Output: first transistor drain that isn't ground or the supply rail
    output_node = None
    for t in transistors:
        if t["drain"] not in ("0", supply_node):
            output_node = t["drain"]
            break
    if output_node is None and transistors:
        output_node = transistors[0]["drain"]   # fallback

    return {
        "signal_source": signal_source,
        "output_node":   output_node or "vout",
        "vdd":           vdd,
    }


# ── Main pipeline ──────────────────────────────────────────────────────

def run_pipeline(netlist_text, output_dir=".",
                 max_iterations=MAX_ITERATIONS,
                 nrmse_threshold=NRMSE_THRESHOLD,
                 provider=None, ai_model=None):
    """
    Full pipeline: SPICE netlist → Verilog-AMS via AI + feedback loop.

    Args:
        netlist_text:    SPICE netlist string
        output_dir:      directory to save the .va file
        max_iterations:  max AI refinement passes   (default 3)
        nrmse_threshold: NRMSE target, 0.05 = 5%   (default)
        provider:        'ollama' | 'anthropic' | None (auto-detect)
        ai_model:        model override (e.g. 'qwen2.5-coder:7b')

    Returns:
        (Path to saved .va file, final NRMSE or None)
    """
    print("=" * 68)
    print(" SPICE → VERILOG-AMS  (AI-AUGMENTED)")
    print("=" * 68)

    # ── Step 1: Parse ────────────────────────────────────────────────
    print("\n[1/4] Parsing netlist...")
    info = parse_netlist(netlist_text)
    print(f"      Signal source : {info['signal_source']}")
    print(f"      Output node   : {info['output_node']}")
    print(f"      Supply        : {info['vdd']} V")

    # ── Step 2: Simulate ─────────────────────────────────────────────
    print("\n[2/4] Running ngspice DC sweep (golden truth)...")
    x, y = None, None
    try:
        runner  = NgspiceRunner()
        results = runner.dc_sweep(netlist_text, {
            "sweep_var": info["signal_source"],   # voltage source name for .dc
            "start":     0.0,
            "stop":      info["vdd"],
            "step":      info["vdd"] / 50,        # ~50 data points
            "observe":   [info["output_node"]],
        })
        x = results[info["signal_source"]]
        y = results[info["output_node"]]
        print(f"      {len(x)} pts: {info['output_node']} "
              f"∈ [{y.min():.3f}, {y.max():.3f}] V")
    except NgspiceError as e:
        print(f"      Failed: {e}")
        print("      Continuing with netlist-only AI generation.")

    # ── Step 3: AI generation + feedback loop ────────────────────────
    print("\n[3/4] AI Agent generating Verilog-AMS...")
    agent   = create_agent(provider=provider, model=ai_model)
    va_code = generate(agent, netlist_text, x, y, info)

    final_nrmse = None
    if x is not None and y is not None:
        for i in range(max_iterations):
            y_model     = evaluate_va_code(va_code, x, info["output_node"])
            nrmse       = compute_nrmse(y, y_model)
            final_nrmse = nrmse
            passed      = nrmse <= nrmse_threshold
            print(f"      Iter {i + 1}: NRMSE={nrmse:.4f}  {'✓ done' if passed else '— refining'}")
            if passed:
                break
            if i < max_iterations - 1:
                va_code = refine(agent, netlist_text, x, y, info, va_code, nrmse)
    else:
        print("      (no simulation data — skipping NRMSE evaluation)")

    # ── Step 4: Save ─────────────────────────────────────────────────
    print("\n[4/4] Saving...")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    va_path = out / "model.va"
    va_path.write_text(va_code)
    print(f"      {va_path}")

    print(f"\n{'=' * 68}")
    if final_nrmse is not None:
        status = "PASS" if final_nrmse <= nrmse_threshold else "FAIL (best attempt saved)"
        print(f" DONE — NRMSE={final_nrmse:.4f}  [{status}]")
    else:
        print(" DONE")
    print("=" * 68)

    return va_path, final_nrmse


# ── Entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    NETLIST = """
* Common-source NMOS amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8
Vin vin 0 DC 0
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        va_path, nrmse = run_pipeline(NETLIST, output_dir=tmp)
        print(f"\n{'=' * 68}")
        print(" GENERATED VERILOG-AMS:")
        print("=" * 68)
        print(va_path.read_text())
