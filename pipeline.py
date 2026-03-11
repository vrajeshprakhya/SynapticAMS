#!/usr/bin/env python3
"""
SynapticAMS: SPICE netlist → Verilog-AMS behavioral model via AI

Pipeline:
  1. Parse netlist  → find signal source, output node, supply voltage
  2. Run ngspice    → DC sweep golden-truth I/O data
  3. Run ngspice    → AC sweep frequency response
  4. AI generates   → Verilog-AMS from netlist + simulation data + AC metrics
  5. Evaluate       → NRMSE vs SPICE ground truth (static models only)
  6. Refine         → feedback loop (up to MAX_ITERATIONS)
  7. Save           → .va file + characterization plot

Requires: ngspice on PATH, and one of:
  - ANTHROPIC_API_KEY set  (uses Claude)
  - Ollama running locally (ollama serve && ollama pull qwen2.5-coder:7b)

Optional: matplotlib (pip install matplotlib) for characterization plots.
"""

import re
import math
import numpy as np
from pathlib import Path
from ngspice_runner import NgspiceRunner, NgspiceError
from ai_agent import create_agent, generate, refine, compute_nrmse, evaluate_va_code

try:
    from spice_flatten import flatten_netlist as _flatten_netlist
except ImportError:
    _flatten_netlist = None

MAX_ITERATIONS  = 3
NRMSE_THRESHOLD = 0.05


# ── Inline comment stripping ────────────────────────────────────────────

def _strip_dollar_comment(line: str) -> str:
    """
    Strip ngspice/HSPICE $ inline comments, respecting quoted strings.

    Per the ngspice manual, '$' starts a comment unless inside a quoted
    string.  SPICE 3F5 does not define this character; this handles the
    ubiquitous real-world convention.
    """
    in_quote = False
    quote_char = None
    for idx, ch in enumerate(line):
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
        elif in_quote and ch == quote_char:
            in_quote = False
            quote_char = None
        elif ch == '$' and not in_quote:
            return line[:idx].rstrip()
    return line


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

    Returns float('nan') for parameter expressions ({expr} or 'expr') and
    any other string that cannot be parsed as a number.  Callers that use
    nan values for sorting or comparison must handle them explicitly.

    Examples:
        "5"         → 5.0
        "1.8"       → 1.8
        "5k"        → 5000.0
        "1.5meg"    → 1500000.0
        "100n"      → 1e-7
        "3.14e-6"   → 3.14e-6
        "1.8V"      → 1.8   (unit suffix V is not a scale, silently ignored)
        "{VDD}"     → nan   (parameter expression — value unknown at parse time)
        "'1.8'"     → nan   (HSPICE quoted expression)
        "Vbias"     → nan   (bare parameter name)
    """
    s = s.strip().lower()
    # Detect parameter expressions that cannot be evaluated statically.
    if not s or s[0] in ('{', "'"):
        return float('nan')
    try:
        return float(s)
    except ValueError:
        pass
    # Per SPICE 3F5 sec2, the numeric form is [DIGIT]+[.DIGIT*] — digits after
    # the decimal are optional, so "5." (no trailing digit) is valid.
    # The alternation covers both forms: "5" / "5." / "5.0" and ".5" / "0.5".
    m = re.match(r"^([+-]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][+-]?\d+)?)(meg|mil|[tgkmunpf])?", s)
    if m:
        return float(m.group(1)) * _SPICE_SCALE.get(m.group(2) or "", 1.0)
    # Bare parameter name or unknown form — value unknowable at parse time.
    return float('nan')


# Keywords that may appear as the 4th token of a V/I source line but are NOT
# a bare DC value.  (Renamed from _VSRC_KEYWORDS to cover I sources too.)
_SRC_KEYWORDS = {"AC", "PULSE", "SIN", "EXP", "PWL", "SFFM", "DISTOF1", "DISTOF2"}
# Keep old name as alias for test-suite compatibility.
_VSRC_KEYWORDS = _SRC_KEYWORDS

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

    # Explicit DC keyword: capture any non-whitespace token after DC.
    # Using \S+ (instead of a numeric-only pattern) lets _parse_spice_number
    # return nan for parameter expressions like {VDD} rather than silently
    # falling through to the implicit-DC path and returning 0.0.
    m = re.search(r"\bDC\s+(\S+)", norm, re.I)
    if m:
        return _parse_spice_number(m.group(1))

    # Implicit DC: bare value is the 4th token (after name, N+, N-).
    # After separator normalization, waveform calls like PULSE(0 5...) become
    # 'PULSE 0 5...', so tokens[3] is just 'PULSE' — no split("(") needed.
    tokens = norm.split()
    if len(tokens) >= 4:
        tok = tokens[3].upper()
        if tok not in _SRC_KEYWORDS:
            return _parse_spice_number(tokens[3])

    return 0.0


def _parse_spice_dc_current(line):
    """
    Extract the DC current from a SPICE independent current source line.

    I sources follow the same syntax as V sources:
        I1 1 0 DC 1u           →  1e-6    (explicit DC keyword)
        I1 1 0 1u              →  1e-6    (implicit DC — bare value)
        I1 1 0 DC 0 AC 1m      →  0.0
        I1 1 0 PULSE(0 1u ...) →  0.0     (transient-only source)
    """
    return _parse_spice_dc_voltage(line)


# Ground node names: SPICE 3F5 specifies only "0"; "gnd" is a common
# simulator extension (ngspice, HSPICE) treated as synonymous here.
_GROUND_NODES = {"0", "gnd"}

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
      - I sources      : same syntax as V; used as signal_source when .DC names
                         one, or when no V sources are present / all are supplies
      - MOSFET (M)     : D G S B model …
      - BJT   (Q)      : C B E [S] model …
      - JFET  (J)      : D G S model …
      - MESFET(Z)      : D G S model …
      - Diode (D)      : N+ N- model …  (N+ used as output candidate)
      - All other elements (R/C/L/G/E/F/H/B/S/W/T/O/U/K) silently ignored

    Sec 3 — Subcircuits:
      - If spice_flatten is available, hierarchical netlists with .SUBCKT /
        X instances are pre-flattened before parsing.
      - .SUBCKT depth is tracked regardless so that elements inside subcircuit
        definitions are never treated as top-level elements.

    Sec 4 — Directives parsed:
      - .DC source start stop step  : sets signal_source directly (more reliable
                                      than the lowest-voltage heuristic); works
                                      for both V and I sources named in the directive
      - .SUBCKT / .ENDS             : depth tracking
      - .END                        : stops parsing (spec: all content after .END
                                      is outside the netlist and must be ignored)
      - All other directives (.MODEL, .AC, .TRAN, .OP, .OPTIONS, …) skipped

    Known limitations (out of scope):
      - Dual/negative supply without .DC : e.g. VEE=-5 DC sorts below Vin=0 and
                                 is chosen as signal_source (wrong). Adding a
                                 .DC directive to the netlist fixes this.
      - Multiple .DC directives  : only the first is used; the second sweep
                                 variable (nested .DC sweep) is ignored.
      - .DC source inside a subcircuit : if the signal V source is defined
                                 inside a .SUBCKT, the flattener renames it
                                 (e.g. Vin → V_X1_in) but the .DC directive is
                                 not updated to match. Standard practice is to
                                 define the signal source at the top level.
      - "gnd" as ground synonym  : SPICE 3F5 specifies only node "0" as ground;
                                 "gnd" is accepted here as a common extension
                                 (ngspice/HSPICE) but other synonyms are not.
      - .PARAM / {expr} / PARAMS: : simulator-specific extensions, not SPICE 3F5.
                                 Parameterised DC values (e.g. DC {VDD}) are
                                 returned as NaN; NaN sources sort last in the
                                 heuristic and trigger the 1.8 V VDD default.

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
    # Strip $ inline comments first so they don't interfere with continuation
    # detection or element parsing (handles non-subckt netlists that bypass
    # the spice_flatten pre-processing step which also strips $).
    joined = []
    for raw in text.splitlines():
        raw = _strip_dollar_comment(raw)
        if raw.startswith("+") and joined:
            joined[-1] = joined[-1] + " " + raw[1:].strip()
        else:
            joined.append(raw)

    # ── Step 2: Parse elements and relevant directives ──────────────────
    # Per spec: the ABSOLUTE first line is unconditionally the circuit title —
    # even if blank or a comment — and is never parsed as an element.
    voltage_sources  = []   # (name, plus_node, dc_voltage)
    current_sources  = []   # (name, plus_node, dc_current)
    transistors      = []   # {"drain": ..., "gate": ...}
    dep_sources      = []   # {"out": ...}  — E/G/F/H/B output nodes
    diodes           = []   # {"anode": ..., "cathode": ...}
    dc_sweep_source  = None # source name from .DC directive, if present
    dc_sweep_start   = None # start value from .DC directive
    dc_sweep_stop    = None # stop value from .DC directive
    dc_sweep_step    = None # step value from .DC directive
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
                # Only the first .DC directive is used; subsequent ones are
                # ignored (multiple .DC = nested sweep, which is out of scope).
                if dc_sweep_source is None:
                    dc_tokens = _normalize_seps(stripped).split()
                    if len(dc_tokens) >= 2:
                        dc_sweep_source = dc_tokens[1]
                    if len(dc_tokens) >= 5:
                        try:
                            dc_sweep_start = _parse_spice_number(dc_tokens[2])
                            dc_sweep_stop  = _parse_spice_number(dc_tokens[3])
                            dc_sweep_step  = _parse_spice_number(dc_tokens[4])
                        except Exception:
                            pass

            elif upper.startswith(".END") and not upper.startswith(".ENDS"):
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

        elif dtype == "I" and len(tokens) >= 3:
            # Independent current source: I name N+ N- [DC] value …
            dc_i = _parse_spice_dc_current(stripped)
            current_sources.append((tokens[0], tokens[1].lower(), dc_i))

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

        elif dtype in ("E", "G") and len(tokens) >= 5:
            # VCVS (E): N+ N- NC+ NC- gain  — N+ is the output
            # VCCS (G): N+ N- NC+ NC- gain  — N+ is the output
            dep_sources.append({"out": tokens[1].lower()})

        elif dtype in ("F", "H") and len(tokens) >= 4:
            # CCCS (F): N+ N- Vnam gain  — N+ is the output
            # CCVS (H): N+ N- Vnam gain  — N+ is the output
            dep_sources.append({"out": tokens[1].lower()})

        elif dtype == "B" and len(tokens) >= 3:
            # Nonlinear source (B): N+ N- V=expr or I=expr  — N+ is the output
            dep_sources.append({"out": tokens[1].lower()})

    if not voltage_sources and not current_sources:
        raise ValueError("No voltage or current sources found in netlist")

    # ── Supply voltage: highest V source by DC value ─────────────────────
    # Parameterised sources ({expr}) have dc_voltage=nan; treat nan as +inf
    # so they never shadow a real supply but still appear in the list.
    def _nan_to_inf(v):
        return v if not math.isnan(v) else float('inf')

    if voltage_sources:
        voltage_sources.sort(key=lambda v: _nan_to_inf(v[2]))
        supply_src  = voltage_sources[-1]           # highest numeric V → supply
        supply_node = supply_src[1]                 # e.g. "vdd"
        sv = supply_src[2]
        vdd = sv if (not math.isnan(sv) and sv > 0.5) else 1.8
    else:
        supply_node = "vdd"
        vdd         = 1.8   # current-only circuit: assume default supply

    # ── Signal source: .DC directive beats the heuristic ────────────────
    # .DC can name either a V or an I source.
    signal_source = None
    if dc_sweep_source:
        dn = dc_sweep_source.upper()
        # Check V sources first, then I sources.
        for src_list in (voltage_sources, current_sources):
            for s in src_list:
                if s[0].upper() == dn:
                    signal_source = s[0]
                    break
            if signal_source:
                break
        if signal_source is None:
            # .DC names a source not in the netlist (e.g. inside a .SUBCKT
            # that was not flattened) — fall back to heuristic.
            signal_source = (voltage_sources[0][0] if voltage_sources
                             else current_sources[0][0])
    else:
        # Heuristic: if I sources exist, prefer the one with lowest |DC|
        # (current-mode circuits typically use Isrc as the swept input).
        # Parameterised sources (nan) sort last so known-zero signals win.
        # Otherwise use the V source with the lowest DC voltage.
        if current_sources:
            current_sources.sort(key=lambda i: _nan_to_inf(abs(i[2])))
            signal_source = current_sources[0][0]
        else:
            signal_source = voltage_sources[0][0]   # lowest DC voltage = signal

    # ── Output node ───────────────────────────────────────────────────────
    # Priority: transistors → dependent sources (E/G/F/H/B) → diodes.
    # current_sources' positive node excluded (typically an input bias node).
    i_src_nodes = {s[1] for s in current_sources}

    def _is_valid_output(node):
        return (node not in _GROUND_NODES
                and node != supply_node
                and node not in i_src_nodes)

    output_node = None
    for t in transistors:
        if _is_valid_output(t["drain"]):
            output_node = t["drain"]
            break
    if output_node is None and transistors:
        output_node = transistors[0]["drain"]    # fallback to first transistor

    # Dependent sources: E/G/F/H/B output node
    if output_node is None:
        for ds in dep_sources:
            if _is_valid_output(ds["out"]):
                output_node = ds["out"]
                break

    # Diodes: last resort
    if output_node is None:
        for d in diodes:
            if _is_valid_output(d["anode"]):
                output_node = d["anode"]
                break

    return {
        "signal_source": signal_source,
        "output_node":   output_node or "vout",
        "vdd":           vdd,
        "dc_start":      dc_sweep_start,  # None if no .DC directive or not parseable
        "dc_stop":       dc_sweep_stop,
        "dc_step":       dc_sweep_step,
    }


# ── DC behavioral metrics ───────────────────────────────────────────────

def _extract_dc_metrics(x, y, vdd):
    """
    Compute key DC behavioral metrics from a DC sweep result.

    Pure numpy — no additional ngspice call.  Called from run_pipeline
    immediately after dc_sweep returns.

    Metrics:
      voh  — output-high voltage: y[0]  (output at lowest sweep input)
      vol  — output-low  voltage: y[-1] (output at highest sweep input)
      vth  — input threshold: first x where Vout crosses (VOH+VOL)/2,
             found by linear interpolation of sign-change crossings
      gain — peak |dVout/dVin|: max of |diff(y)/diff(x)| across sweep

    Edge cases handled:
      - Flat output (y constant): gain=0, vth=midpoint of sweep
      - No midpoint crossing: vth=x at index closest to midpoint
      - Single-point sweep: gain=0, vth=x[0]

    Args:
        x:   1D numpy array of input values (e.g. Vin, V)
        y:   1D numpy array of output values (e.g. Vout, V)
        vdd: supply voltage (float) — for context, not used in math

    Returns:
        dict: {'voh': float, 'vol': float, 'vth': float, 'gain': float}
    """
    voh      = float(y[0])
    vol      = float(y[-1])
    midpoint = (voh + vol) / 2.0

    # Switching threshold: first crossing of (VOH+VOL)/2 by linear interp
    vth = float(x[len(x) // 2])          # fallback: midpoint of sweep range
    diff_from_mid = y - midpoint
    for i in range(len(diff_from_mid) - 1):
        if diff_from_mid[i] * diff_from_mid[i + 1] <= 0:
            dy = float(diff_from_mid[i + 1] - diff_from_mid[i])
            if abs(dy) > 1e-15:
                t   = -float(diff_from_mid[i]) / dy
                vth = float(x[i]) + t * float(x[i + 1] - x[i])
            else:
                vth = float(x[i])
            break
    else:
        # No crossing found — use x at index closest to midpoint
        vth = float(x[int(np.argmin(np.abs(diff_from_mid)))])

    # Peak gain: max |dVout/dVin|; guard against zero-length dx steps
    if len(x) >= 2:
        dx_arr   = np.diff(x.astype(float))
        dy_arr   = np.diff(y.astype(float))
        nonzero  = dx_arr != 0
        gain     = float(np.max(np.abs(dy_arr[nonzero] / dx_arr[nonzero]))) \
                   if np.any(nonzero) else 0.0
    else:
        gain = 0.0

    return {'voh': voh, 'vol': vol, 'vth': vth, 'gain': gain}


def _get_source_positive_node(netlist_text, device_name):
    """
    Given a V or I source device name (e.g. 'Vtx_p'), return the name of its
    positive terminal node (e.g. 'tx_in_p') by scanning the raw netlist.

    SPICE element syntax (§4.1):  Vxxx N+ N- <DC val> <AC mag> ...
      tokens[0] = device name, tokens[1] = N+ (positive node).

    This is needed because parse_netlist() returns the DEVICE name for
    signal_source (to use in .DC commands), but ac_sweep() needs the NODE
    name to find which source to inject AC into.

    Returns None if the device is not found.
    """
    dn_upper = device_name.upper()
    for line in netlist_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('*'):
            continue
        tokens = stripped.split()
        if tokens[0].upper() == dn_upper and len(tokens) >= 2:
            return tokens[1]
    return None


def _extract_ac_metrics(ac_results, output_node):
    """
    Derive key frequency-domain metrics from an AC sweep result dict.

    Args:
        ac_results:  dict returned by NgspiceRunner.ac_sweep()
                     {frequency: np.array, node: {magnitude_db, magnitude, phase}}
        output_node: the node name whose response to analyse

    Returns:
        dict with:
          dc_gain_db     — gain at the lowest swept frequency (≈ DC), in dB
          dc_gain_linear — same gain in V/V
          bw_3db_hz      — -3 dB bandwidth in Hz (None if never drops 3 dB)
          frequencies    — np.array of swept frequencies
          magnitude_db   — np.array of gain vs frequency in dB
          phase          — np.array of phase in degrees
        Returns None if ac_results is empty or output_node is missing.
    """
    freqs = ac_results.get('frequency', np.array([]))
    if output_node not in ac_results or len(freqs) == 0:
        return None
    node_data = ac_results[output_node]
    mag_db = node_data['magnitude_db']
    phase  = node_data['phase']
    if len(mag_db) == 0:
        return None

    dc_gain_db     = float(mag_db[0])
    dc_gain_linear = 10 ** (dc_gain_db / 20.0)
    target_db      = dc_gain_db - 3.0

    # Find -3 dB frequency: first point where gain drops below dc_gain - 3 dB.
    # Log-linear interpolation gives a more accurate crossing than linear.
    bw_3db = None
    for i in range(1, len(mag_db)):
        if float(mag_db[i]) < target_db:
            f1, f2 = float(freqs[i - 1]), float(freqs[i])
            m1, m2 = float(mag_db[i - 1]), float(mag_db[i])
            t = (target_db - m1) / (m2 - m1) if abs(m2 - m1) > 1e-12 else 0.5
            t = max(0.0, min(1.0, t))
            bw_3db = f1 * (f2 / f1) ** t
            break

    return {
        'dc_gain_db':     dc_gain_db,
        'dc_gain_linear': dc_gain_linear,
        'bw_3db_hz':      bw_3db,
        'frequencies':    freqs,
        'magnitude_db':   mag_db,
        'phase':          phase,
    }


def _save_plots(output_dir, x_dc, y_dc, info, ac_metrics):
    """
    Save a characterization PNG to output_dir/characterization.png.

    Left panel  — DC transfer characteristic (Vin vs Vout).
    Right panel — AC Bode magnitude plot (frequency vs gain in dB),
                  shown only when ac_metrics is not None.

    Requires matplotlib.  Returns the Path if saved, None if matplotlib is
    unavailable or if the save fails.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')          # non-interactive: no display needed
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    has_ac = (ac_metrics is not None
              and len(ac_metrics.get('frequencies', [])) > 0)

    fig, axes = plt.subplots(1, 2 if has_ac else 1,
                             figsize=(12 if has_ac else 6, 4))

    # ── DC panel ─────────────────────────────────────────────────────────
    ax_dc = axes[0] if has_ac else axes
    ax_dc.plot(x_dc, y_dc, 'b-', linewidth=1.5)
    ax_dc.axhline(0, color='k', linewidth=0.4, alpha=0.5)
    ax_dc.axvline(0, color='k', linewidth=0.4, alpha=0.5)
    ax_dc.set_xlabel(f"V({info['signal_source']})  [V]")
    ax_dc.set_ylabel(f"V({info['output_node']})  [V]")
    ax_dc.set_title('DC Transfer Characteristic')
    ax_dc.grid(True, alpha=0.3)

    # ── AC Bode panel ────────────────────────────────────────────────────
    if has_ac:
        ax_ac = axes[1]
        freqs  = ac_metrics['frequencies']
        mag_db = ac_metrics['magnitude_db']
        ax_ac.semilogx(freqs, mag_db, 'r-', linewidth=1.5)
        if ac_metrics['bw_3db_hz']:
            bw = ac_metrics['bw_3db_hz']
            ax_ac.axvline(bw, color='gray', linestyle='--', linewidth=1,
                          label=f'−3 dB BW: {bw/1e6:.1f} MHz')
            ax_ac.axhline(ac_metrics['dc_gain_db'] - 3,
                          color='gray', linestyle='--', linewidth=1)
            ax_ac.legend(fontsize=8)
        ax_ac.set_xlabel('Frequency  [Hz]')
        ax_ac.set_ylabel('Gain  [dB]')
        ax_ac.set_title('AC Frequency Response (Bode)')
        ax_ac.grid(True, which='both', alpha=0.3)

    plt.tight_layout()
    try:
        plot_path = Path(output_dir) / 'characterization.png'
        plt.savefig(str(plot_path), dpi=150, bbox_inches='tight')
        return plot_path
    except Exception:
        return None
    finally:
        plt.close()


def _is_dynamic_model(va_code):
    """
    Return True if va_code uses time-domain or frequency-domain constructs
    (laplace_nd, laplace_zd, zi_nd, zi_zd, ddt, idt, idtmod).

    Dynamic models cannot be evaluated by the Python-based evaluate_va_code()
    regex evaluator, so NRMSE validation must be skipped for them.
    """
    dynamic_keywords = [
        'laplace_nd', 'laplace_zd', 'zi_nd', 'zi_zd',
        'ddt(', 'idt(', 'idtmod(',
    ]
    return any(kw in va_code for kw in dynamic_keywords)


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
    print("\n[1/5] Parsing netlist...")
    info = parse_netlist(netlist_text)
    print(f"      Signal source : {info['signal_source']}")
    print(f"      Output node   : {info['output_node']}")
    print(f"      Supply        : {info['vdd']} V")

    # ── Step 2: DC sweep ─────────────────────────────────────────────
    print("\n[2/5] Running ngspice DC sweep (golden truth)...")
    x, y = None, None
    runner = NgspiceRunner()
    try:
        # Use .DC parameters from the netlist when present (e.g. differential
        # circuits with negative start voltage); fall back to 0→vdd/50pts.
        _dc_start = info["dc_start"] if info["dc_start"] is not None else 0.0
        _dc_stop  = info["dc_stop"]  if info["dc_stop"]  is not None else info["vdd"]
        _dc_step  = info["dc_step"]  if info["dc_step"]  is not None else info["vdd"] / 50
        results = runner.dc_sweep(netlist_text, {
            "sweep_var": info["signal_source"],
            "start":     _dc_start,
            "stop":      _dc_stop,
            "step":      _dc_step,
            "observe":   [info["output_node"]],
        })
        x = results[info["signal_source"]]
        y = results[info["output_node"]]
        print(f"      {len(x)} pts: {info['output_node']} "
              f"∈ [{y.min():.3f}, {y.max():.3f}] V")
    except NgspiceError as e:
        print(f"      Failed: {e}")
        print("      Continuing with netlist-only AI generation.")

    # Compute DC behavioral metrics from sweep data (pure numpy, no extra
    # ngspice run).  These are passed to the AI to anchor key operating
    # points (VOH, VOL, Vth, gain) in the generated Verilog-AMS model.
    metrics = None
    if x is not None and y is not None:
        metrics = _extract_dc_metrics(x, y, info["vdd"])
        print(f"      VOH={metrics['voh']:.3f}V  VOL={metrics['vol']:.3f}V  "
              f"Vth={metrics['vth']:.3f}V  Gain={metrics['gain']:.1f}V/V")

    # ── Step 3: AC sweep ─────────────────────────────────────────────
    # The AC sweep linearises the circuit around its DC bias point and sweeps
    # frequency.  This gives us the bandwidth of the SerDes amplifier chain,
    # which the AI uses to generate a dynamic (first-order laplace) VA model
    # instead of a purely static V(out)=f(V(in)) expression.
    print("\n[3/5] Running ngspice AC sweep (frequency response)...")
    ac_metrics = None
    try:
        # ac_sweep needs the POSITIVE TERMINAL NODE of the signal source (e.g.
        # 'tx_in_p'), not the device name ('Vtx_p') that parse_netlist returns.
        # _get_source_positive_node extracts tokens[1] from the source line.
        ac_input_node = _get_source_positive_node(netlist_text,
                                                   info['signal_source'])
        if ac_input_node is None:
            ac_input_node = info['signal_source']   # fallback to device name

        ac_results = runner.ac_sweep(netlist_text, {
            'sweep_type':   'dec',
            'n_points':     20,          # 20 pts/decade — enough for Bode plot
            'start_freq':   1e3,         # 1 kHz  (well below any pole of interest)
            'stop_freq':    10e9,        # 10 GHz (above any useful SerDes BW)
            'input_node':   ac_input_node,
            'output_nodes': [info['output_node']],
        })
        ac_metrics = _extract_ac_metrics(ac_results, info['output_node'])
        if ac_metrics is not None:
            bw_str = (f"{ac_metrics['bw_3db_hz'] / 1e6:.1f} MHz"
                      if ac_metrics['bw_3db_hz'] else "N/A (flat across range)")
            print(f"      DC gain={ac_metrics['dc_gain_db']:.1f} dB  "
                  f"-3dB BW={bw_str}")
        else:
            print("      AC result empty — skipping AC metrics.")
    except Exception as e:
        print(f"      AC sweep failed: {e}")
        print("      Continuing without frequency-domain data.")

    # ── Step 4: AI generation + feedback loop ────────────────────────
    print("\n[4/5] AI Agent generating Verilog-AMS...")
    agent   = create_agent(provider=provider, model=ai_model)
    va_code = generate(agent, netlist_text, x, y, info,
                       metrics=metrics, ac_metrics=ac_metrics)

    final_nrmse = None
    if x is not None and y is not None:
        if _is_dynamic_model(va_code):
            # Dynamic models (laplace_nd, ddt, etc.) cannot be evaluated by
            # the Python regex evaluator in evaluate_va_code().  The model is
            # saved as-is; a separate Verilog-AMS simulator is needed to
            # validate it against the SPICE golden data.
            print("      Dynamic model detected (laplace/ddt) — "
                  "NRMSE validation skipped.")
        else:
            for i in range(max_iterations):
                y_model     = evaluate_va_code(va_code, x, info["output_node"])
                nrmse       = compute_nrmse(y, y_model)
                final_nrmse = nrmse
                passed      = nrmse <= nrmse_threshold
                print(f"      Iter {i + 1}: NRMSE={nrmse:.4f}  "
                      f"{'✓ done' if passed else '— refining'}")
                if passed:
                    break
                if i < max_iterations - 1:
                    va_code = refine(agent, netlist_text, x, y, info,
                                     va_code, nrmse)
    else:
        print("      (no simulation data — skipping NRMSE evaluation)")

    # ── Step 5: Save ─────────────────────────────────────────────────
    print("\n[5/5] Saving...")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    va_path = out / "model.va"
    va_path.write_text(va_code)
    print(f"      model  : {va_path}")

    if x is not None and y is not None:
        plot_path = _save_plots(output_dir, x, y, info, ac_metrics)
        if plot_path:
            print(f"      plots  : {plot_path}")
        else:
            print("      plots  : (matplotlib not installed — skipped)")

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
    import sys
    import tempfile

    _DEFAULT_NETLIST = """
* Common-source NMOS amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8
Vin vin 0 DC 0
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""
    if len(sys.argv) > 1:
        netlist_path = Path(sys.argv[1])
        if not netlist_path.exists():
            print(f"Error: file not found: {netlist_path}", file=sys.stderr)
            sys.exit(1)
        NETLIST = netlist_path.read_text()
        output_dir = str(netlist_path.parent / (netlist_path.stem + "_output"))
        va_path, nrmse = run_pipeline(NETLIST, output_dir=output_dir)
    else:
        NETLIST = _DEFAULT_NETLIST
        with tempfile.TemporaryDirectory() as tmp:
            va_path, nrmse = run_pipeline(NETLIST, output_dir=tmp)
            print(f"\n{'=' * 68}")
            print(" GENERATED VERILOG-AMS:")
            print("=" * 68)
            print(va_path.read_text())
