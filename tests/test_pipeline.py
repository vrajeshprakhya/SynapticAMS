#!/usr/bin/env python3
"""
SynapticAMS — Test Suite

Groups:
  A  Unit tests          — no external dependencies
  B  Feedback loop       — AI mocked, ngspice mocked
  C  Live Ollama         — requires `ollama serve` with a code model
  D  Live ngspice        — requires ngspice on PATH
  E  Full end-to-end     — requires both

Run:
  python tests/test_pipeline.py              # all groups
  python tests/test_pipeline.py --skip-live  # A + B only  (~2 s)
  python tests/test_pipeline.py --group A
  python tests/test_pipeline.py --group E
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np


# ── Sample circuits ────────────────────────────────────────────────────

COMMON_SOURCE = """
* Common-source NMOS amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8
Vin vin 0 DC 0
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

NMOS_SIMPLE = """
* Simple NMOS (no load — drain tied to VDD)
M1 vd vg 0 0 NMOS W=1u L=1u
VDD vd 0 DC 1.8
Vin vg 0 DC 0
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

KNOWN_GOOD_VAMS = """\
`include "disciplines.vams"

// Common-source NMOS: uses V(vin) directly so the equation evaluator can parse it.
module vout_model(output electrical vout, input electrical vin);
    parameter real Vth   = 0.4;
    parameter real k     = 1.0e-3;
    parameter real RD    = 1.0e4;
    parameter real VDD   = 1.8;
    parameter real delta = 0.036;

    analog begin
        if (V(vin) < Vth)
            V(vout) <+ VDD;
        else
            V(vout) <+ VDD - k * (V(vin) - Vth) * (V(vin) - Vth)
                           * (1.0 / (1.0 + exp(-(V(vin) - Vth) / delta))) * RD;
    end
endmodule
"""


# ── Helpers ────────────────────────────────────────────────────────────

def make_sweep_data(n=51, vdd=1.8):
    """Synthetic DC sweep: inverting amplifier shape."""
    x = np.linspace(0, vdd, n)
    Vth, k, RD = 0.4, 1e-3, 1e4
    id_ = np.where(x >= Vth, k * (x - Vth) ** 2, 0.0)
    y   = np.clip(vdd - id_ * RD, 0, vdd)
    return x, y


def _approx(val, abs_tol=None, rel_tol=None):
    """Minimal pytest.approx replacement."""
    _abs = __builtins__["abs"] if isinstance(__builtins__, dict) else __builtins__.abs
    class _A:
        def __init__(self, v, a, r):
            self.v, self.a, self.r = v, a, r
        def __eq__(self, other):
            if self.a is not None:
                return _abs(other - self.v) <= self.a
            tol = (self.r * _abs(self.v)) if self.r else 1e-6
            return _abs(other - self.v) <= tol
        def __repr__(self):
            return f"≈{self.v}"
    return _A(val, abs_tol, rel_tol)


# ══════════════════════════════════════════════════════════════════════
# GROUP A — Unit tests (no external deps)
# ══════════════════════════════════════════════════════════════════════

def a_parse_netlist_finds_signal_source():
    from pipeline import parse_netlist
    info = parse_netlist(COMMON_SOURCE)
    assert info["signal_source"].upper() == "VIN", info
    assert info["output_node"] == "vout", info
    assert info["vdd"] == _approx(1.8, abs_tol=0.01)

def a_parse_netlist_finds_supply():
    from pipeline import parse_netlist
    info = parse_netlist(COMMON_SOURCE)
    assert info["vdd"] > 1.0

def a_parse_netlist_simple_nmos():
    from pipeline import parse_netlist
    info = parse_netlist(NMOS_SIMPLE)
    assert info["signal_source"].upper() == "VIN"
    # drain of M1 is vd — which is the supply node, so we fall back to it
    assert info["output_node"] is not None

def a_compute_nrmse_identical():
    from ai_agent import compute_nrmse
    x, y = make_sweep_data()
    assert compute_nrmse(y, y) == _approx(0.0, abs_tol=1e-10)

def a_compute_nrmse_all_nan():
    from ai_agent import compute_nrmse
    x, y = make_sweep_data()
    assert compute_nrmse(y, np.full(len(y), np.nan)) == float("inf")

def a_compute_nrmse_zero_model():
    from ai_agent import compute_nrmse
    x, y = make_sweep_data()
    nrmse = compute_nrmse(y, np.zeros_like(y))
    assert nrmse > 0.5, f"Expected large NRMSE for zero model, got {nrmse}"

def a_compute_nrmse_flat_reference():
    from ai_agent import compute_nrmse
    y = np.ones(20)
    assert compute_nrmse(y, y * 1.1) == _approx(0.0, abs_tol=1e-9)

def a_evaluate_known_good_model():
    from ai_agent import evaluate_va_code
    x, y_true = make_sweep_data()
    y_pred = evaluate_va_code(KNOWN_GOOD_VAMS, x, "vout")
    valid = ~np.isnan(y_pred)
    assert np.sum(valid) > 10, "Too many NaN values"
    from ai_agent import compute_nrmse
    nrmse = compute_nrmse(y_true, y_pred)
    assert nrmse < 0.20, f"NRMSE {nrmse:.4f} too high for known-good model"

def a_evaluate_returns_nan_for_garbage():
    from ai_agent import evaluate_va_code
    x, _ = make_sweep_data()
    y = evaluate_va_code("this is not verilog", x, "vout")
    assert np.all(np.isnan(y))

def a_clean_code_strips_markdown():
    from ai_agent import clean_code
    raw = "```verilog\n`include \"disciplines.vams\"\n```"
    result = clean_code(raw)
    assert "```" not in result
    assert "`include" in result

def a_clean_code_strips_verilogams_fence():
    from ai_agent import clean_code
    raw = "```verilog-ams\nmodule foo();\nendmodule\n```"
    result = clean_code(raw)
    assert "```" not in result

def a_clean_code_passes_clean_input():
    from ai_agent import clean_code
    code = "`include \"disciplines.vams\"\nmodule foo();\nendmodule"
    assert clean_code(code) == code


# ── I-source and new pipeline.py features ────────────────────────────

def a_parse_netlist_with_current_source():
    """parse_netlist picks the I source as signal when .DC names it."""
    from pipeline import parse_netlist
    netlist = """\
* Current-mode test
M1 vout vin 0 0 NMOS W=1u L=1u
Ibias vin 0 DC 10u
VDD vdd 0 DC 1.8
.DC Ibias 0 100u 1u
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
"""
    info = parse_netlist(netlist)
    assert info["signal_source"].upper() == "IBIAS", info

def a_parse_netlist_isource_heuristic():
    """parse_netlist heuristic: lowest |DC| current source picked as signal."""
    from pipeline import parse_netlist
    netlist = """\
* I-source only circuit (no .DC directive)
Q1 vout vin 0 NPN
Isig vin 0 DC 1u
Ibig vcc 0 DC 1m
.model NPN NPN (IS=1e-14 BF=100)
"""
    info = parse_netlist(netlist)
    # Isig has smaller |DC| so should be chosen
    assert info["signal_source"].upper() == "ISIG", info

def a_parse_spice_dc_current_explicit():
    """_parse_spice_dc_current handles explicit DC keyword."""
    from pipeline import _parse_spice_dc_current
    result = _parse_spice_dc_current("I1 vp vn DC 1u")
    assert abs(result - 1e-6) < 1e-18

def a_parse_spice_dc_current_implicit():
    """_parse_spice_dc_current handles bare value (implicit DC)."""
    from pipeline import _parse_spice_dc_current
    result = _parse_spice_dc_current("I1 vp vn 500n")
    assert abs(result - 5e-7) < 1e-19

# ── spice_flatten new features ────────────────────────────────────────

def a_spice_flatten_dollar_comment():
    """$ inline comments are stripped during flattening."""
    from spice_flatten import SpiceFlattener
    netlist = """\
Title
R1 a b 1k $ this is a resistor inline comment
M1 d g s b NMOS $ mosfet with comment
"""
    flat = SpiceFlattener()
    flat.parse_text(netlist)
    flat_text = flat.flatten_text()
    assert "$" not in flat_text, f"$ not stripped:\n{flat_text!r}"
    assert "R1" in flat_text
    assert "M1" in flat_text

def a_spice_flatten_dollar_comment_in_quoted_string():
    """$ inside a quoted string must NOT be stripped."""
    from spice_flatten import SpiceFlattener
    line = 'R1 a b "my$net" $ real comment'
    result = SpiceFlattener._strip_inline_comment(line)
    # The real comment should be stripped but the quoted $ should remain
    assert '"my$net"' in result
    assert "real comment" not in result

def a_spice_flatten_params_keyword():
    """PARAMS: in X instances does not cause port mismatch errors."""
    from spice_flatten import flatten_netlist
    netlist = """\
Title
.SUBCKT myinv in out vdd vss
M1 out in vdd vdd PMOS W=2u L=100n
M2 out in vss vss NMOS W=1u L=100n
.ENDS myinv
X1 net_in net_out vdd 0 myinv PARAMS: W=2u L=100n
VDD vdd 0 DC 1.8
"""
    flat = flatten_netlist(netlist)
    # Should not raise; flat text should contain flattened transistors
    assert "PMOS" in flat or "M1" in flat.upper() or "NMOS" in flat

def a_spice_flatten_nested_subckt():
    """Nested .SUBCKT definitions are registered and can be instantiated."""
    from spice_flatten import flatten_netlist
    netlist = """\
Title
.SUBCKT outer in out
  .SUBCKT inner a b
    R1 a b 1k
  .ENDS inner
  X_inner in out inner
.ENDS outer
Xouter vin vout outer
Vin vin 0 DC 1
"""
    flat = flatten_netlist(netlist)
    # R1 from the inner subckt should appear in the flattened result
    assert "R1" in flat or "1k" in flat

# ── ngspice_runner new helpers ────────────────────────────────────────

def a_ngspice_find_source_for_node():
    """_find_voltage_source_for_node maps node name to voltage source name."""
    from ngspice_runner import NgspiceRunner
    runner = NgspiceRunner()
    netlist = """\
Title
Vin vin 0 DC 0
VDD vdd 0 DC 1.8
"""
    result = runner._find_voltage_source_for_node(netlist, "vin")
    assert result.upper() == "VIN", f"Expected Vin, got {result}"

def a_ngspice_find_source_isource():
    """_find_voltage_source_for_node also finds I sources by their positive node."""
    from ngspice_runner import NgspiceRunner
    runner = NgspiceRunner()
    netlist = """\
Title
Ibias ibias_node 0 DC 1u
VDD vdd 0 DC 1.8
"""
    result = runner._find_voltage_source_for_node(netlist, "ibias_node")
    assert result.upper() == "IBIAS", f"Expected Ibias, got {result}"

def a_ngspice_find_source_no_match():
    """_find_voltage_source_for_node returns the node name when no source matches."""
    from ngspice_runner import NgspiceRunner
    runner = NgspiceRunner()
    netlist = """\
Title
VDD vdd 0 DC 1.8
"""
    result = runner._find_voltage_source_for_node(netlist, "vout")
    assert result == "vout"


# ── $ inline comments in parse_netlist (non-subckt path) ─────────────

def a_parse_netlist_dollar_comment_stripped():
    """$ comments in flat netlists are stripped before element parsing."""
    from pipeline import parse_netlist
    netlist = """\
* Title line
M1 vout vin 0 0 NMOS W=1u L=1u $ drain is the output
VDD vdd 0 DC 1.8 $ supply
Vin vin 0 DC 0 $ signal
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
"""
    info = parse_netlist(netlist)
    assert info["signal_source"].upper() == "VIN"
    assert info["output_node"] == "vout"
    assert info["vdd"] == _approx(1.8, abs_tol=0.01)


# ── .PARAM / {expr} — NaN handling ───────────────────────────────────

def a_parse_spice_number_param_expr_nan():
    """_parse_spice_number returns nan for {expr} parameter expressions."""
    import math
    from pipeline import _parse_spice_number
    assert math.isnan(_parse_spice_number("{VDD}"))
    assert math.isnan(_parse_spice_number("'1.8'"))
    assert math.isnan(_parse_spice_number("Vbias"))

def a_parse_netlist_param_vdd_fallback():
    """Parameterised VDD ({expr}) falls back to 1.8 V default."""
    from pipeline import parse_netlist
    netlist = """\
* Parameterised supply
.PARAM VDD=1.8
M1 vout vin 0 0 NMOS W=1u L=1u
VDD vdd 0 DC {VDD}
Vin vin 0 DC 0
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
"""
    info = parse_netlist(netlist)
    # NaN-valued VDD falls to 1.8 default; real Vin (DC=0) wins as signal
    assert info["signal_source"].upper() == "VIN"
    assert info["vdd"] == _approx(1.8, abs_tol=0.01)

def a_parse_netlist_param_signal_not_chosen():
    """Parameterised V source (NaN DC) is not chosen as signal over a real 0 V source."""
    from pipeline import parse_netlist
    netlist = """\
* Parameterised signal test
M1 vout vin 0 0 NMOS W=1u L=1u
Vparam vbias 0 DC {Vbias}
Vin vin 0 DC 0
VDD vdd 0 DC 1.8
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
"""
    info = parse_netlist(netlist)
    # Vparam has NaN → sorts last; Vin with DC=0 is the real signal
    assert info["signal_source"].upper() == "VIN"


# ── Dependent source output node detection ───────────────────────────

def a_parse_netlist_evcvs_output_node():
    """E (VCVS) output node is detected when no transistors present."""
    from pipeline import parse_netlist
    netlist = """\
* Simple VCVS amplifier
E1 vout 0 vin 0 10
VDD vdd 0 DC 1.8
Vin vin 0 DC 0
"""
    info = parse_netlist(netlist)
    assert info["output_node"] == "vout", info

def a_parse_netlist_bsource_output_node():
    """B (nonlinear source) output node is detected when no transistors present."""
    from pipeline import parse_netlist
    netlist = """\
* Nonlinear B source
B1 vout 0 V=tanh(V(vin))
VDD vdd 0 DC 1.8
Vin vin 0 DC 0
"""
    info = parse_netlist(netlist)
    assert info["output_node"] == "vout", info


# ── spice_flatten: .END terminates parsing ────────────────────────────

def a_spice_flatten_end_stops_parsing():
    """.END terminates flattening; elements after it are ignored."""
    from spice_flatten import flatten_netlist
    netlist = """\
Title
R1 a b 1k
.END
* Everything below should be ignored
R2 c d 99k
"""
    flat = flatten_netlist(netlist)
    assert "R1" in flat
    assert "R2" not in flat

def a_spice_flatten_end_in_subckt_file():
    """.END stops parsing so garbage after it doesn't cause errors."""
    from spice_flatten import SpiceFlattener
    netlist = """\
Title
.SUBCKT mymod a b
R1 a b 1k
.ENDS mymod
.END
.SUBCKT phantom x y
R2 x y 99k
.ENDS phantom
"""
    f = SpiceFlattener()
    f.parse_text(netlist)
    # phantom subcircuit defined after .END must NOT be registered
    assert "PHANTOM" not in f.subcircuits


# ── spice_flatten: .MODEL tracking prevents model-name renaming ───────

def a_spice_flatten_model_name_not_renamed():
    """Model names declared with .MODEL are never prefixed as if they were nets."""
    from spice_flatten import flatten_netlist
    netlist = """\
Title
.SUBCKT inv in out vdd vss
M1 out in vdd vdd PMOS W=2u L=100n
M2 out in vss vss NMOS W=1u L=100n
.ENDS inv
.MODEL PMOS PMOS (LEVEL=1 VTO=-0.5 KP=50u)
.MODEL NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u)
X1 vin vout vdd 0 inv
VDD vdd 0 DC 1.8
"""
    flat = flatten_netlist(netlist)
    # Model names PMOS and NMOS must appear unchanged, not prefixed
    assert "PMOS" in flat
    assert "NMOS" in flat
    # Prefixed versions must NOT appear
    assert "X1_PMOS" not in flat and "_PMOS" not in flat.replace("PMOS", "")
    assert "X1_NMOS" not in flat and "_NMOS" not in flat.replace("NMOS", "")


# ── spice_flatten: Q BJT 4th (substrate) terminal renamed ─────────────

def a_spice_flatten_bjt_4terminal_renamed():
    """Q BJT substrate (4th) node is correctly renamed inside a subcircuit."""
    from spice_flatten import flatten_netlist
    netlist = """\
Title
.SUBCKT bjt_cell in out sub
Q1 out in 0 sub NPN
.ENDS bjt_cell
.MODEL NPN NPN (IS=1e-14 BF=100)
X1 vin vout vsub bjt_cell
Vin vin 0 DC 0
"""
    flat = flatten_netlist(netlist)
    # The substrate port 'sub' maps to connected node 'vsub' at the instance
    assert "vsub" in flat, f"vsub not found in flat netlist:\n{flat}"
    # The model name NPN must remain unmodified
    assert "NPN" in flat


# ── spice_flatten: F source Vnam correctly renamed ────────────────────

def a_spice_flatten_f_source_vnam_renamed():
    """F (CCCS) controlling V-source reference is renamed with the subcircuit prefix."""
    from spice_flatten import flatten_netlist
    netlist = """\
Title
.SUBCKT cccs_cell in out
Vsense in 0 DC 0
F1 out 0 Vsense 10
.ENDS cccs_cell
X1 vin vout cccs_cell
Vin vin 0 DC 0
"""
    flat = flatten_netlist(netlist)
    # Vsense inside cccs_cell should be renamed to V_X1_sense (or similar prefixed form)
    # The F1 reference should match — check that the un-prefixed "Vsense" is not used
    # as the F1 Vnam while "V_X1_sense" is the actual device name
    lines = [l.strip() for l in flat.splitlines() if l.strip() and not l.strip().startswith("*")]
    f_line = next((l for l in lines if l.upper().startswith("F")), None)
    v_line = next((l for l in lines if l.upper().startswith("V") and "SENSE" in l.upper()), None)
    assert f_line is not None, f"No F device in flat netlist:\n{flat}"
    assert v_line is not None, f"No Vsense device in flat netlist:\n{flat}"
    # Both lines should reference the same (prefixed) V-source name
    f_tokens = f_line.split()
    v_tokens = v_line.split()
    assert len(f_tokens) >= 4, f"F line malformed: {f_line}"
    assert f_tokens[3].upper() == v_tokens[0].upper(), (
        f"F Vnam '{f_tokens[3]}' does not match V device name '{v_tokens[0]}'"
    )


# ── spice_flatten: K mutual inductor L-names renamed ─────────────────

def a_spice_flatten_k_mutual_renamed():
    """K mutual inductor L1/L2 device references are renamed with the subcircuit prefix."""
    from spice_flatten import flatten_netlist
    netlist = """\
Title
.SUBCKT coupled_pair a b c d
L1 a b 1u
L2 c d 1u
K12 L1 L2 0.9
.ENDS coupled_pair
X1 n1 n2 n3 n4 coupled_pair
Vin n1 0 DC 0
"""
    flat = flatten_netlist(netlist)
    lines = [l.strip() for l in flat.splitlines() if l.strip() and not l.strip().startswith("*")]
    k_line = next((l for l in lines if l.upper().startswith("K")), None)
    assert k_line is not None, f"No K device in flat netlist:\n{flat}"
    k_tokens = k_line.split()
    assert len(k_tokens) >= 3, f"K line malformed: {k_line}"
    # The L references in K must have been prefixed (not bare "L1" / "L2")
    assert k_tokens[1] != "L1", f"L1 not renamed in K line: {k_line}"
    assert k_tokens[2] != "L2", f"L2 not renamed in K line: {k_line}"


# ══════════════════════════════════════════════════════════════════════
# GROUP B — Feedback loop with mocked AI + ngspice
# ══════════════════════════════════════════════════════════════════════

class _MockAgent:
    """Always returns syntactically valid but inaccurate Verilog-AMS."""
    model = "mock"
    def __init__(self, responses=None):
        self.calls    = 0
        self.responses = responses or []
    def chat(self, system, user):
        resp = self.responses[self.calls] if self.calls < len(self.responses) else KNOWN_GOOD_VAMS
        self.calls += 1
        return resp


def b_early_exit_when_model_passes():
    from pipeline import run_pipeline
    x, y = make_sweep_data()
    agent = _MockAgent(responses=[KNOWN_GOOD_VAMS])
    with tempfile.TemporaryDirectory() as tmp:
        with patch("pipeline.create_agent", return_value=agent), \
             patch("pipeline.NgspiceRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.dc_sweep.return_value = {"Vin": x, "vout": y}
            mock_runner_cls.return_value = mock_runner
            va_path, nrmse = run_pipeline(COMMON_SOURCE, output_dir=tmp,
                                          max_iterations=3)
        assert va_path.exists()
        assert nrmse is not None
        # Agent called exactly once (first pass was good enough)
        assert agent.calls == 1

def b_iterates_max_times_when_always_failing():
    """When model never passes, pipeline runs exactly max_iterations generate calls."""
    from pipeline import run_pipeline
    x, y = make_sweep_data()
    bad_code = "`include \"disciplines.vams\"\nmodule m(output electrical o, input electrical i);\nanalog begin V(o) <+ 0.0; end\nendmodule"
    MAX = 2
    agent = _MockAgent(responses=[bad_code] * (MAX + 1))
    with tempfile.TemporaryDirectory() as tmp:
        with patch("pipeline.create_agent", return_value=agent), \
             patch("pipeline.NgspiceRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.dc_sweep.return_value = {"Vin": x, "vout": y}
            mock_runner_cls.return_value = mock_runner
            va_path, nrmse = run_pipeline(COMMON_SOURCE, output_dir=tmp,
                                          max_iterations=MAX)
    assert agent.calls == MAX   # 1 generate + (MAX-1) refines
    assert nrmse > 0.05

def b_ngspice_failure_runs_without_nrmse():
    """If ngspice fails, pipeline still generates a .va file (no NRMSE)."""
    from pipeline import run_pipeline
    from ngspice_runner import NgspiceError
    agent = _MockAgent(responses=[KNOWN_GOOD_VAMS])
    with tempfile.TemporaryDirectory() as tmp:
        with patch("pipeline.create_agent", return_value=agent), \
             patch("pipeline.NgspiceRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.dc_sweep.side_effect = NgspiceError("test failure")
            mock_runner_cls.return_value = mock_runner
            va_path, nrmse = run_pipeline(COMMON_SOURCE, output_dir=tmp)
        assert va_path.exists(), "File should exist inside tmp dir"
        assert nrmse is None                  # no simulation → no NRMSE
        assert "module" in va_path.read_text()

def b_refine_receives_nrmse():
    """The refine call receives the NRMSE from the previous iteration."""
    from pipeline import run_pipeline
    from ai_agent import refine as real_refine
    x, y = make_sweep_data()
    bad = "`include \"disciplines.vams\"\nmodule m(output electrical o, input electrical i);\nanalog begin V(o) <+ 0.0; end\nendmodule"
    good = KNOWN_GOOD_VAMS
    agent = _MockAgent(responses=[bad, good])
    captured_nrmse = []
    original_refine = real_refine
    def mock_refine(ag, netlist, xd, yd, info, code, nrmse):
        captured_nrmse.append(nrmse)
        return original_refine(ag, netlist, xd, yd, info, code, nrmse)
    with tempfile.TemporaryDirectory() as tmp:
        with patch("pipeline.create_agent", return_value=agent), \
             patch("pipeline.refine", side_effect=mock_refine), \
             patch("pipeline.NgspiceRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.dc_sweep.return_value = {"Vin": x, "vout": y}
            mock_runner_cls.return_value = mock_runner
            run_pipeline(COMMON_SOURCE, output_dir=tmp, max_iterations=2)
    assert len(captured_nrmse) == 1
    assert captured_nrmse[0] > 0.05     # bad model should have high NRMSE


# ══════════════════════════════════════════════════════════════════════
# GROUP C — Live Ollama
# ══════════════════════════════════════════════════════════════════════

def c_ollama_server_reachable():
    from ai_agent import OllamaAgent
    models = OllamaAgent.available_models()
    assert len(models) > 0, "No models pulled — run: ollama pull qwen2.5-coder:7b"
    print(f"\n         Models: {', '.join(models)}")

def c_ollama_chat_returns_text(model):
    from ai_agent import OllamaAgent
    agent = OllamaAgent(model=model)
    resp = agent.chat("Reply with exactly: TEST_OK", "ping")
    assert len(resp.strip()) > 0

def c_ai_generates_module_keyword(model):
    from ai_agent import OllamaAgent, generate
    x, y = make_sweep_data()
    agent = OllamaAgent(model=model)
    info  = {"signal_source": "Vin", "output_node": "vout", "vdd": 1.8}
    code  = generate(agent, COMMON_SOURCE, x, y, info)
    print(f"\n         Generated ({len(code)} chars)")
    assert "module" in code, "No 'module' keyword in output"
    return code

def c_ai_generates_analog_block(code):
    assert "analog" in code, "No 'analog' block"

def c_ai_generates_voltage_assignment(code):
    assert "<+" in code, "No <+ assignment operator"

def c_ai_output_has_no_fences(code):
    assert "```" not in code, "Output contains markdown fences"

def c_ai_refine_produces_code(model):
    from ai_agent import OllamaAgent, refine
    x, y  = make_sweep_data()
    info  = {"signal_source": "Vin", "output_node": "vout", "vdd": 1.8}
    agent = OllamaAgent(model=model)
    bad   = "`include \"disciplines.vams\"\nmodule m(output electrical o, input electrical i);\nanalog begin V(o) <+ 0.0; end\nendmodule"
    result = refine(agent, COMMON_SOURCE, x, y, info, bad, nrmse=0.95)
    assert "module" in result


# ══════════════════════════════════════════════════════════════════════
# GROUP D — Live ngspice
# ══════════════════════════════════════════════════════════════════════

def d_ngspice_dc_sweep_returns_data():
    from ngspice_runner import NgspiceRunner
    runner  = NgspiceRunner()
    results = runner.dc_sweep(COMMON_SOURCE, {
        "sweep_var": "Vin",
        "start":     0.0,
        "stop":      1.8,
        "step":      0.1,
        "observe":   ["vout"],
    })
    assert "Vin" in results or "vin" in results, f"No sweep data: {list(results)}"
    key = "Vin" if "Vin" in results else "vin"
    assert len(results[key]) >= 5

def d_ngspice_golden_truth_is_inverting():
    """Common-source amplifier: vout should decrease as vin increases past Vth."""
    from ngspice_runner import NgspiceRunner
    runner  = NgspiceRunner()
    results = runner.dc_sweep(COMMON_SOURCE, {
        "sweep_var": "Vin",
        "start":     0.0,
        "stop":      1.8,
        "step":      0.036,
        "observe":   ["vout"],
    })
    vout = results["vout"] if "vout" in results else results.get("Vout", None)
    assert vout is not None, f"No vout in results: {list(results)}"
    diff = np.diff(vout[~np.isnan(vout)])
    assert np.sum(diff < 0) > len(diff) * 0.3, "vout should mostly decrease (inverting amp)"


# ══════════════════════════════════════════════════════════════════════
# GROUP E — Full end-to-end  (ngspice + Ollama)
# ══════════════════════════════════════════════════════════════════════

def e_full_pipeline_generates_va_file(model, tmp_dir):
    """
    SPICE → ngspice → AI → .va file.
    Checks: file created, non-empty, contains 'module'.
    """
    from pipeline import run_pipeline
    va_path, nrmse = run_pipeline(
        COMMON_SOURCE,
        output_dir=tmp_dir,
        max_iterations=1,
        provider="ollama",
        ai_model=model,
    )
    assert va_path.exists(), f"File not found: {va_path}"
    content = va_path.read_text()
    assert len(content) > 10, "Output file is nearly empty"
    assert "module" in content, "Output .va has no 'module' keyword"
    print(f"\n         Saved: {va_path}  ({len(content)} chars)")
    if nrmse is not None:
        print(f"         NRMSE={nrmse:.4f}  passed={nrmse <= 0.05}")
    return content, nrmse

def e_nrmse_is_computed_or_none(result):
    content, nrmse = result
    # nrmse is either a float or None (when ngspice had no data)
    if nrmse is not None:
        assert isinstance(nrmse, float)
        assert nrmse >= 0.0


# ══════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════

def run_tests(groups, model=None):
    from ai_agent import OllamaAgent
    import shutil

    has_ollama  = OllamaAgent.is_available()
    has_ngspice = shutil.which("ngspice") is not None
    ollama_model = model
    if has_ollama and not ollama_model:
        available = OllamaAgent.available_models()
        preferred = ["qwen2.5-coder", "codellama", "deepseek-coder", "llama3"]
        ollama_model = next(
            (a for p in preferred for a in available if a.startswith(p)),
            available[0] if available else "qwen2.5-coder:7b",
        )

    W = 55
    passed = failed = 0
    failures = []

    def run(label, fn, *args):
        nonlocal passed, failed
        try:
            result = fn(*args)
            print(f"  \033[32m✓\033[0m  {label}")
            passed += 1
            return result
        except Exception as e:
            print(f"  \033[31m✗\033[0m  {label}")
            print(f"         {type(e).__name__}: {e}")
            failed += 1
            failures.append(label)
            return None

    skip_live = "E" not in groups and "C" not in groups and "D" not in groups
    skip_c    = "C" not in groups or not has_ollama
    skip_d    = "D" not in groups or not has_ngspice
    skip_e    = "E" not in groups or not has_ollama or not has_ngspice

    print("=" * W)
    print("  SynapticAMS — Test Suite")
    print("-" * W)
    if has_ollama:
        print(f"  Ollama  : {ollama_model}")
    else:
        print("  Ollama  : not running")
    print(f"  ngspice : {'found' if has_ngspice else 'not found'}")
    print("=" * W)

    # ── Group A ──────────────────────────────────────────────────────
    if "A" in groups:
        print(f"\n{'-'*W}")
        print("  A  |  Unit Tests")
        print("-" * W)
        run("[A] parse_netlist finds signal source",   a_parse_netlist_finds_signal_source)
        run("[A] parse_netlist finds supply voltage",  a_parse_netlist_finds_supply)
        run("[A] parse_netlist simple NMOS",           a_parse_netlist_simple_nmos)
        run("[A] compute_nrmse = 0 for identical",     a_compute_nrmse_identical)
        run("[A] compute_nrmse = inf for all-NaN",     a_compute_nrmse_all_nan)
        run("[A] compute_nrmse is high for zero model",a_compute_nrmse_zero_model)
        run("[A] compute_nrmse = 0 for flat reference",a_compute_nrmse_flat_reference)
        run("[A] evaluate_va_code on known-good model",a_evaluate_known_good_model)
        run("[A] evaluate_va_code returns NaN for garbage", a_evaluate_returns_nan_for_garbage)
        run("[A] clean_code strips ``` markdown",      a_clean_code_strips_markdown)
        run("[A] clean_code strips verilog-ams fence", a_clean_code_strips_verilogams_fence)
        run("[A] clean_code passes clean input",       a_clean_code_passes_clean_input)
        # I-source / pipeline.py additions
        run("[A] parse_netlist: .DC names I source",   a_parse_netlist_with_current_source)
        run("[A] parse_netlist: I-source heuristic",   a_parse_netlist_isource_heuristic)
        run("[A] _parse_spice_dc_current explicit DC", a_parse_spice_dc_current_explicit)
        run("[A] _parse_spice_dc_current implicit DC", a_parse_spice_dc_current_implicit)
        # spice_flatten additions
        run("[A] spice_flatten: $ comments stripped",  a_spice_flatten_dollar_comment)
        run("[A] spice_flatten: $ in quoted str kept", a_spice_flatten_dollar_comment_in_quoted_string)
        run("[A] spice_flatten: PARAMS: on X line",    a_spice_flatten_params_keyword)
        run("[A] spice_flatten: nested .SUBCKT",       a_spice_flatten_nested_subckt)
        # ngspice_runner additions
        run("[A] ngspice: find V source for node",     a_ngspice_find_source_for_node)
        run("[A] ngspice: find I source for node",     a_ngspice_find_source_isource)
        run("[A] ngspice: find source no match",       a_ngspice_find_source_no_match)
        # $ inline comments in parse_netlist (non-subckt path)
        run("[A] parse_netlist: $ stripped (no subckt)",a_parse_netlist_dollar_comment_stripped)
        # .PARAM / {expr} NaN handling
        run("[A] _parse_spice_number: {expr} → nan",   a_parse_spice_number_param_expr_nan)
        run("[A] parse_netlist: {VDD} falls back 1.8V",a_parse_netlist_param_vdd_fallback)
        run("[A] parse_netlist: param src not chosen", a_parse_netlist_param_signal_not_chosen)
        # Dependent source output node detection
        run("[A] parse_netlist: E source output node", a_parse_netlist_evcvs_output_node)
        run("[A] parse_netlist: B source output node", a_parse_netlist_bsource_output_node)
        # spice_flatten: .END termination
        run("[A] spice_flatten: .END stops parsing",   a_spice_flatten_end_stops_parsing)
        run("[A] spice_flatten: .END ignores phantom", a_spice_flatten_end_in_subckt_file)
        # spice_flatten: .MODEL tracking
        run("[A] spice_flatten: model names not renamed",a_spice_flatten_model_name_not_renamed)
        # spice_flatten: Q 4-terminal BJT
        run("[A] spice_flatten: BJT 4th terminal",     a_spice_flatten_bjt_4terminal_renamed)
        # spice_flatten: F source Vnam
        run("[A] spice_flatten: F Vnam renamed",       a_spice_flatten_f_source_vnam_renamed)
        # spice_flatten: K mutual inductance
        run("[A] spice_flatten: K L-refs renamed",     a_spice_flatten_k_mutual_renamed)

    # ── Group B ──────────────────────────────────────────────────────
    if "B" in groups:
        print(f"\n{'-'*W}")
        print("  B  |  Feedback Loop (mocked AI + ngspice)")
        print("-" * W)
        run("[B] early exit when model passes",        b_early_exit_when_model_passes)
        run("[B] iterates max times when always failing", b_iterates_max_times_when_always_failing)
        run("[B] ngspice failure → .va without NRMSE", b_ngspice_failure_runs_without_nrmse)
        run("[B] refine receives NRMSE",               b_refine_receives_nrmse)

    # ── Group C ──────────────────────────────────────────────────────
    if "C" in groups:
        print(f"\n{'-'*W}")
        reason = f"(ollama not running)" if not has_ollama else ""
        print(f"  C  |  Live Ollama  {reason}")
        print("-" * W)
        if skip_c:
            print("  (skipped)")
        else:
            run("[C] Ollama server reachable",             c_ollama_server_reachable)
            run("[C] Ollama chat returns text",            c_ollama_chat_returns_text, ollama_model)
            code = run("[C] AI generates 'module' keyword",c_ai_generates_module_keyword, ollama_model)
            if code:
                run("[C] AI generates 'analog' block",     c_ai_generates_analog_block, code)
                run("[C] AI generates <+ assignment",       c_ai_generates_voltage_assignment, code)
                run("[C] AI output has no markdown fences", c_ai_output_has_no_fences, code)
            run("[C] AI refine produces code",             c_ai_refine_produces_code, ollama_model)

    # ── Group D ──────────────────────────────────────────────────────
    if "D" in groups:
        print(f"\n{'-'*W}")
        reason = "(ngspice not found)" if not has_ngspice else ""
        print(f"  D  |  Live ngspice  {reason}")
        print("-" * W)
        if skip_d:
            print("  (skipped)")
        else:
            run("[D] ngspice DC sweep returns data",       d_ngspice_dc_sweep_returns_data)
            run("[D] ngspice: vout is inverting",          d_ngspice_golden_truth_is_inverting)

    # ── Group E ──────────────────────────────────────────────────────
    if "E" in groups:
        print(f"\n{'-'*W}")
        reason = "(requires ngspice + Ollama)" if skip_e else f"model={ollama_model}"
        print(f"  E  |  Full End-to-End  ({reason})")
        print("-" * W)
        if skip_e:
            print("  (skipped)")
        else:
            with tempfile.TemporaryDirectory() as tmp:
                result = run("[E] full pipeline → .va file",
                             e_full_pipeline_generates_va_file, ollama_model, tmp)
                if result is not None:
                    run("[E] NRMSE computed or None",
                        e_nrmse_is_computed_or_none, result)

    # ── Summary ───────────────────────────────────────────────────────
    total = passed + failed
    print(f"\n{'=' * W}")
    if failed == 0:
        print(f"  Results: {passed}/{total} passed  \033[32m— all passed\033[0m")
    else:
        print(f"  Results: {passed}/{total} passed  |  \033[31m{failed} FAILED\033[0m")
        for f in failures:
            print(f"    \033[31m✗\033[0m {f}")
    print("=" * W)
    return failed


# ══════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SynapticAMS test suite")
    parser.add_argument("--group",     help="Run a single group (A/B/C/D/E)")
    parser.add_argument("--skip-live", action="store_true",
                        help="Run A+B only (no ngspice/Ollama needed)")
    parser.add_argument("--model",     help="Ollama model override")
    args = parser.parse_args()

    if args.skip_live:
        groups = list("AB")
    elif args.group:
        groups = [args.group.upper()]
    else:
        groups = list("ABCDE")

    sys.exit(run_tests(groups, model=args.model))
