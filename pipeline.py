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

try:
    from spice_flatten import flatten_netlist as _flatten_netlist
except ImportError:
    _flatten_netlist = None

MAX_ITERATIONS  = 3
NRMSE_THRESHOLD = 0.05


# ── SPICE number / voltage parsing ─────────────────────────────────────

# Scale suffixes from the SPICE 3F5 spec (case-insensitive).
# Note: 'M' = milli (1e-3), NOT mega — use 'meg' for 1e6.
_SPICE_SCALE = {
    "meg": 1e6, "mil": 25.4e-6,
    "t": 1e12, "g": 1e9,  "k": 1e3,
    "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
}

# SPICE 3F5 sec2: fields are separated by blanks, commas, '=', or parentheses.
_FIELD_SEP_RE = re.compile(r"[,=()]")

def _normalize_seps(line):
    """Replace all SPICE field separators (comma, =, parentheses) with spaces."""
    return _FIELD_SEP_RE.sub(" ", line)


def _parse_spice_number(s):
    """
    Parse a SPICE numeric string including optional scale suffix.

    Examples:
        "5"       → 5.0
        "1.8"     → 1.8
        "5k"      → 5000.0
        "1.5meg"  → 1500000.0
        "100n"    → 1e-7
        "3.14e-6" → 3.14e-6
        "1.8V"    → 1.8   (unit suffix V is not a scale, silently ignored)
    """
    s = s.strip().lower()
    try:
        return float(s)
    except ValueError:
        pass
    m = re.match(r"^([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)(meg|mil|[tgkmunpf])?", s)
    if m:
        return float(m.group(1)) * _SPICE_SCALE.get(m.group(2) or "", 1.0)
    return 0.0


# Keywords that may appear as the 4th token of a V-source line but are NOT
# a bare DC value.
_VSRC_KEYWORDS = {"AC", "PULSE", "SIN", "EXP", "PWL", "SFFM", "DISTOF1", "DISTOF2"}

def _parse_spice_dc_voltage(line):
    """
    Extract the DC voltage from a SPICE independent voltage source line.

    Normalizes field separators first so comma/paren-delimited netlists work.

    Handles all legal V-source forms from the SPICE 3F5 spec:
        V1 1 0 DC 5            →  5.0    (explicit DC keyword)
        V1 1 0 DC 5k           →  5000.0 (scale suffix)
        V1 1 0 DC 1.8V         →  1.8    (unit suffix, ignored)
        V1 1 0 5               →  5.0    (implicit DC — bare value, no keyword)
        V1 1 0 1.8             →  1.8
        V1 1 0 DC 0 AC 1       →  0.0
        V1 1 0 AC 1            →  0.0    (AC-only source, no DC component)
        V1 1 0 PULSE(0 5 ...)  →  0.0    (transient-only source)
        V1 1 0 SIN(0 1 1MEG)   →  0.0
        V1,1,0,DC,5            →  5.0    (comma-separated)
    """
    norm = _normalize_seps(line)

    # Explicit DC keyword: capture number + optional scale suffix
    m = re.search(
        r"\bDC\s+([+-]?[\d.]+(?:[eE][+-]?\d+)?(?:meg|mil|[tgkmunpf])?)",
        norm, re.I,
    )
    if m:
        return _parse_spice_number(m.group(1))

    # Implicit DC: bare value is the 4th token (after name, N+, N-).
    # After separator normalization, waveform calls like PULSE(0 5...) become
    # 'PULSE 0 5...', so tokens[3] is just 'PULSE' — no split("(") needed.
    tokens = norm.split()
    if len(tokens) >= 4:
        tok = tokens[3].upper()
        if tok not in _VSRC_KEYWORDS:
            return _parse_spice_number(tokens[3])

    return 0.0


# ── Netlist parsing ─────────────────────────────────────────────────────

def parse_netlist(text):
    """
    Extract simulation parameters from a SPICE netlist (SPICE 3F5 format).

    Handles per spec:

    Sec 2 — Syntax:
      - Title line     : absolute first line is unconditionally the title
      - Continuation   : '+' in column 1 extends the previous line
      - Comments       : '*' in column 1 OR any leading whitespace (SPICE 3)
      - Field seps     : blank, comma, '=', '(' and ')' are equivalent

    Sec 3 — Elements parsed:
      - V sources      : DC keyword optional; all scale suffixes (k/meg/u/n/…)
      - MOSFET (M)     : D G S B model …
      - BJT   (Q)      : C B E [S] model …
      - JFET  (J)      : D G S model …
      - MESFET(Z)      : D G S model …
      - Diode (D)      : N+ N- model …  (N+ used as output candidate)
      - All other elements (R/C/L/I/G/E/F/H/B/S/W/T/O/U/K) silently ignored

    Sec 3 — Subcircuits:
      - If spice_flatten is available, hierarchical netlists with .SUBCKT /
        X instances are pre-flattened before parsing.
      - .SUBCKT depth is tracked regardless so that elements inside subcircuit
        definitions are never treated as top-level elements.

    Sec 4 — Directives parsed:
      - .DC source start stop step  : sets signal_source directly (more reliable
                                      than the lowest-voltage heuristic)
      - .SUBCKT / .ENDS             : depth tracking
      - .END                        : stops parsing (spec: all content after .END
                                      is outside the netlist and must be ignored)
      - All other directives (.MODEL, .AC, .TRAN, .OP, .OPTIONS, …) skipped

    Known limitations (out of scope):
      - I-source signal inputs : .DC Isrc 0 1u 10n has no matching V source,
                                 so signal_source falls back to the lowest-DC-V
                                 heuristic, which may pick a supply rail instead.
      - Dual/negative supply without .DC : e.g. VEE=-5 DC sorts below Vin=0 and
                                 is chosen as signal_source (wrong). Adding a
                                 .DC directive to the netlist fixes this.
      - .PARAM / {expr} / PARAMS: : simulator-specific extensions, not SPICE 3F5.
      - $ inline comments          : ngspice extension, not SPICE 3F5.

    Returns dict with:
        signal_source  — voltage source name to sweep  (e.g. "Vin")
        output_node    — net to observe                (e.g. "vout")
        vdd            — supply voltage in volts
    """
    # ── Step 0: Flatten subcircuits if spice_flatten is available ───────
    # Detects any .SUBCKT definition in the text and flattens before parsing,
    # so X instances become visible as regular M/Q/J/Z/D/V elements.
    if _flatten_netlist is not None and re.search(
            r"^\s*\.subckt\b", text, re.I | re.M):
        text = _flatten_netlist(text)

    # ── Step 1: Join continuation lines ('+' must be in column 1) ──────
    joined = []
    for raw in text.splitlines():
        if raw.startswith("+") and joined:
            joined[-1] = joined[-1] + " " + raw[1:].strip()
        else:
            joined.append(raw)

    # ── Step 2: Parse elements and relevant directives ──────────────────
    # Per spec: the ABSOLUTE first line is unconditionally the circuit title —
    # even if blank or a comment — and is never parsed as an element.
    voltage_sources  = []   # (name, plus_node, dc_voltage)
    transistors      = []   # {"drain": ..., "gate": ...}
    diodes           = []   # {"anode": ..., "cathode": ...}
    dc_sweep_source  = None # source name from .DC directive, if present
    subckt_depth     = 0    # >0 means we are inside a .SUBCKT block
    title_seen       = False

    for line in joined:
        # Title: consume the absolute first line unconditionally.
        if not title_seen:
            title_seen = True
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue                              # blank or '*' comment

        # SPICE 3 rule: any line whose first character is whitespace is a comment.
        if line[0] in (" ", "\t"):
            continue

        # ── Directive handling ──────────────────────────────────────────
        if stripped.startswith("."):
            upper = stripped.upper()

            if upper.startswith(".SUBCKT"):
                subckt_depth += 1

            elif upper.startswith(".ENDS"):
                subckt_depth = max(0, subckt_depth - 1)

            elif upper.startswith(".DC") and subckt_depth == 0:
                # .DC source start stop step [src2 start2 stop2 step2]
                # The first source is the inner (signal) sweep variable.
                dc_tokens = _normalize_seps(stripped).split()
                if len(dc_tokens) >= 2:
                    dc_sweep_source = dc_tokens[1]

            elif upper == ".END":
                # Per spec sec2: .END marks the absolute end of the netlist.
                # Anything after this line is outside the circuit description
                # and must be ignored.
                break

            continue   # never parse a directive line as an element

        # Skip element lines that are inside a .SUBCKT definition.
        # (Normally resolved by the pre-flattener; this is a safety net.)
        if subckt_depth > 0:
            continue

        # Normalize field separators before tokenizing (sec2: comma, =, ( and )
        # are all valid delimiters equivalent to a blank).
        tokens = _normalize_seps(stripped).split()
        if not tokens:
            continue
        dtype = tokens[0][0].upper()

        if dtype == "V" and len(tokens) >= 3:
            dc_v = _parse_spice_dc_voltage(stripped)
            voltage_sources.append((tokens[0], tokens[1].lower(), dc_v))

        elif dtype in ("M", "J", "Z") and len(tokens) >= 5:
            # M: Drain Gate Source Bulk  model …
            # J: Drain Gate Source       model …
            # Z: Drain Gate Source       model …  (MESFET)
            transistors.append({"drain": tokens[1].lower(),
                                 "gate":  tokens[2].lower()})

        elif dtype == "Q" and len(tokens) >= 4:
            # Q: Collector Base Emitter [Substrate] model …
            transistors.append({"drain": tokens[1].lower(),   # collector
                                 "gate":  tokens[2].lower()})  # base

        elif dtype == "D" and len(tokens) >= 3:
            # D: N+ (anode) N- (cathode) model …
            # N+ is stored as a fallback output-node candidate.
            diodes.append({"anode":   tokens[1].lower(),
                           "cathode": tokens[2].lower()})

    if not voltage_sources:
        raise ValueError("No voltage sources found in netlist")

    voltage_sources.sort(key=lambda v: v[2])     # ascending by DC voltage
    supply_src  = voltage_sources[-1]            # highest V → supply

    supply_node = supply_src[1]                  # e.g. "vdd"
    vdd         = supply_src[2] if supply_src[2] > 0.5 else 1.8

    # ── Signal source: .DC directive beats the heuristic ────────────────
    signal_source = None
    if dc_sweep_source:
        # Case-insensitive match against the V sources we found.
        for vs in voltage_sources:
            if vs[0].upper() == dc_sweep_source.upper():
                signal_source = vs[0]
                break
        if signal_source is None:
            # .DC names a source not present as a V element (e.g. a current
            # source or a source inside a subcircuit) — fall back to heuristic.
            signal_source = voltage_sources[0][0]
    else:
        signal_source = voltage_sources[0][0]    # lowest DC voltage = signal

    # ── Output node: first device terminal not on ground or supply ───────
    output_node = None
    for t in transistors:
        if t["drain"] not in ("0", supply_node):
            output_node = t["drain"]
            break
    if output_node is None and transistors:
        output_node = transistors[0]["drain"]    # fallback to first transistor

    # If no transistors found, try diode anodes as a last resort.
    if output_node is None:
        for d in diodes:
            if d["anode"] not in ("0", supply_node):
                output_node = d["anode"]
                break

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
