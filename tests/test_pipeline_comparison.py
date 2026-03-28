#!/usr/bin/env python3
"""
tests/test_pipeline_comparison.py

Compares AI pipeline vs non-AI pipeline (and hybrid combinations) across
all netlists in examples/netlists/. Scores every generated Verilog-AMS
model and prints a final ranking.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PREREQUISITES (checked at startup — nothing is silently skipped):
  REQUIRED
    ngspice           on PATH            all DC/AC simulations
    AI agent          Ollama or          Test 1 AI, Test 2, Test 3
                      ANTHROPIC_API_KEY
  OPTIONAL
    non-AI pipeline   pipeline_ext       Test 1 non-AI, Test 2 warm-start
    openvaf           on PATH            Test 4 OSDI compile
    ngspice --osdi    .osdi directive    Test 4 OSDI simulation
    anthropic pkg     pip install        Test 3 AI judge (Claude as judge)
    matplotlib        pip install        DC/AC plots
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tests
-----
  Test 1  Head-to-head          AI vs non-AI, Python NRMSE proxy
  Test 2  Warm-start            non-AI numeric params → AI refinement
  Test 3  AI judge              both VAs → Claude picks/merges → re-score
  Test 4  OSDI validation       compile VA with OpenVAF, simulate in ngspice
                                [SKIPPED unless openvaf + OSDI ngspice present]

Usage
-----
  python tests/test_pipeline_comparison.py                 # all netlists
  python tests/test_pipeline_comparison.py --netlist examples/netlists/bjt_amplifier.cir
  python tests/test_pipeline_comparison.py --skip-ai       # non-AI only
  python tests/test_pipeline_comparison.py --skip-nonai    # AI only
  python tests/test_pipeline_comparison.py --skip-judge    # skip Test 3
"""

import argparse
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import numpy as np

# ── repo root on path ────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ── imports — every failure is reported, never swallowed ────────────────────

def _try_import(module_path, friendly_name):
    """Import module_path; return (obj, None) or (None, error_string)."""
    try:
        parts = module_path.split(".")
        mod = __import__(module_path, fromlist=[parts[-1]])
        return mod, None
    except Exception as e:
        return None, str(e)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 1 — Capability detection (verbose, no silent skips)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_capabilities() -> dict:
    """
    Check every dependency. Print a status line for each.
    Returns a caps dict used by every test to decide what to skip.
    """
    print("\n" + "=" * 68)
    print(" CAPABILITY CHECK")
    print("=" * 68)

    caps = {}

    # ── ngspice ──────────────────────────────────────────────────────────────
    ngspice_bin = subprocess.run(
        ["which", "ngspice"], capture_output=True, text=True
    ).stdout.strip()
    caps["ngspice"] = bool(ngspice_bin)
    _cap_line("ngspice binary", caps["ngspice"],
              ok_detail=ngspice_bin,
              fail_detail="not found on PATH — all simulations will be skipped",
              required=True)

    # ── ngspice OSDI support (.osdi directive) ────────────────────────────────
    osdi_test = subprocess.run(
        ["ngspice", "-b"],
        input=".title osdi_probe\n.osdi /dev/null\n.end\n",
        capture_output=True, text=True
    )
    osdi_ngspice = "unimplemented" not in osdi_test.stderr.lower()
    caps["ngspice_osdi"] = osdi_ngspice
    _cap_line(
        "ngspice OSDI support (.osdi directive)",
        osdi_ngspice,
        ok_detail="ngspice compiled with --enable-osdi",
        fail_detail=(
            "ngspice compiled WITHOUT --enable-osdi  "
            "(Homebrew bottle does not include it). "
            "Fix: brew uninstall ngspice && brew install ngspice --HEAD "
            "--with-osdi  OR  compile from source with ./configure --enable-osdi"
        ),
    )

    # ── OpenVAF ──────────────────────────────────────────────────────────────
    openvaf_bin = subprocess.run(
        ["which", "openvaf"], capture_output=True, text=True
    ).stdout.strip()
    caps["openvaf"] = bool(openvaf_bin)
    _cap_line(
        "openvaf binary",
        caps["openvaf"],
        ok_detail=openvaf_bin,
        fail_detail=(
            "not found on PATH. "
            "No pre-built macOS ARM64 binary exists (last release v23.5.0 had no assets). "
            "To build from source: install Rust via rustup, then "
            "'cargo install --git https://github.com/pascalkuthe/OpenVAF'. "
            "Also requires LLVM 14+ ('brew install llvm')."
        ),
    )

    # ── AI agent (Ollama or Anthropic) ───────────────────────────────────────
    ollama_ok = bool(
        subprocess.run(["which", "ollama"], capture_output=True).stdout.strip()
    )
    anthropic_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    caps["ai_agent"] = ollama_ok or anthropic_key

    if ollama_ok and anthropic_key:
        ai_detail = "Ollama + ANTHROPIC_API_KEY (will use ANTHROPIC_API_KEY)"
    elif anthropic_key:
        ai_detail = "ANTHROPIC_API_KEY set"
    elif ollama_ok:
        ai_detail = "Ollama found (will use Ollama)"
    else:
        ai_detail = (
            "neither Ollama nor ANTHROPIC_API_KEY found — "
            "Tests 1-AI, 2, and 3 will be skipped"
        )
    _cap_line("AI agent", caps["ai_agent"],
              ok_detail=ai_detail, fail_detail=ai_detail)

    # ── anthropic Python package (needed for AI judge) ────────────────────────
    try:
        import anthropic as _anthropic  # noqa: F401
        caps["anthropic_pkg"] = True
        _cap_line("anthropic Python package", True, ok_detail="available (Test 3 judge enabled)")
    except ImportError:
        caps["anthropic_pkg"] = False
        _cap_line(
            "anthropic Python package",
            False,
            fail_detail=(
                "not installed — Test 3 AI judge requires Claude API directly. "
                "Fix: pip install anthropic  (also set ANTHROPIC_API_KEY)"
            ),
        )

    # ── non-AI pipeline ───────────────────────────────────────────────────────
    nonai_mod, nonai_err = _try_import(
        "pipeline_ext.complete_pipeline", "non-AI pipeline"
    )
    caps["nonai_pipeline"] = nonai_mod is not None
    caps["_nonai_mod"] = nonai_mod
    _cap_line(
        "non-AI pipeline (pipeline_ext.complete_pipeline)",
        caps["nonai_pipeline"],
        ok_detail="available (Tests 1-nonAI and 2 enabled)",
        fail_detail=f"import failed: {nonai_err} — Tests 1-nonAI and 2 will be skipped",
    )

    # ── oscillator equivalence checker ───────────────────────────────────────
    osc_mod, osc_err = _try_import("oscillator_equivalence", "oscillator equivalence")
    caps["oscillator_checker"] = osc_mod is not None
    _cap_line(
        "oscillator_equivalence module",
        caps["oscillator_checker"],
        ok_detail="available (frequency-domain VCO equivalence enabled)",
        fail_detail=f"import failed: {osc_err} — oscillator equivalence checks will be skipped",
    )

    # ── matplotlib ────────────────────────────────────────────────────────────
    try:
        import matplotlib as _mpl  # noqa: F401
        caps["matplotlib"] = True
        _cap_line("matplotlib", True, ok_detail="DC/AC plots will be saved")
    except ImportError:
        caps["matplotlib"] = False
        _cap_line(
            "matplotlib",
            False,
            fail_detail="not installed — plots will be skipped. Fix: pip install matplotlib",
        )

    # ── spice_flatten ─────────────────────────────────────────────────────────
    flat_mod, flat_err = _try_import("spice_flatten", "SPICE flattener")
    caps["spice_flatten"] = flat_mod is not None
    _cap_line(
        "spice_flatten module",
        caps["spice_flatten"],
        ok_detail="subcircuit flattening available",
        fail_detail=f"import failed: {flat_err} — subcircuit flattening will be skipped",
    )

    # ── Python NRMSE evaluator limitations ───────────────────────────────────
    print()
    print("  [NOTE] Python NRMSE evaluator (evaluate_va_code) limitations:")
    print("         - Cannot evaluate intermediate variables (real vgs; vgs = V(in); ...)")
    print("         - Cannot evaluate laplace_nd / ddt / idt (dynamic models)")
    print("         - For these, NRMSE will show 'inf' or 'N/A (dynamic)'")
    print("         - True validation requires OpenVAF + OSDI ngspice (Test 4)")

    print()
    n_blocked = sum(1 for k, v in caps.items()
                    if not k.startswith("_") and not v
                    and k not in ("oscillator_checker", "matplotlib", "anthropic_pkg",
                                  "spice_flatten", "ngspice_osdi", "openvaf"))
    if n_blocked:
        print(f"  [WARN] {n_blocked} required capability(ies) missing — some tests will be skipped.")
    else:
        print("  [OK]   All required capabilities present.")

    return caps


def _cap_line(name: str, ok: bool, *, ok_detail="", fail_detail="", required=False):
    status = "[OK]     " if ok else ("[MISSING]" if required else "[SKIPPED]")
    print(f"  {status} {name}")
    if ok and ok_detail:
        print(f"           → {ok_detail}")
    if not ok and fail_detail:
        # Wrap long lines
        wrapped = textwrap.fill(fail_detail, width=72, subsequent_indent="             ")
        print(f"           ✗ {wrapped}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 2 — Shared helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _score(va_code: str, x, y, output_node: str) -> str:
    """
    Score va_code with the Python NRMSE proxy.
    Returns a formatted string like '0.0341' or 'inf' or 'N/A (dynamic)' or 'N/A (eval error)'.
    """
    from ai_agent import evaluate_va_code, compute_nrmse  # noqa: PLC0415
    from pipeline import _is_dynamic_model  # noqa: PLC0415
    if _is_dynamic_model(va_code):
        return "N/A (dynamic — needs OSDI)"
    try:
        y_pred = evaluate_va_code(va_code, x, output_node)
        nrmse = compute_nrmse(y, y_pred)
        if np.isnan(nrmse) or np.isinf(nrmse):
            return "inf (eval returned NaN — intermediate vars or unsupported construct)"
        return f"{nrmse:.4f}"
    except Exception as e:
        return f"N/A (eval error: {e})"


def _load_netlist(path: Path) -> str:
    return path.read_text()


def _strip_control_blocks(netlist_text: str) -> str:
    """
    Remove .control/.endc blocks from a netlist before embedding it in a
    simulation deck. NgspiceRunner builds its own .control block; nesting
    them causes 'Nesting of .control statements is not allowed' in ngspice.
    """
    out, in_block = [], False
    for line in netlist_text.splitlines():
        upper = line.strip().upper()
        if upper.startswith(".CONTROL"):
            in_block = True
            continue
        if upper.startswith(".ENDC"):
            in_block = False
            continue
        if not in_block:
            out.append(line)
    return "\n".join(out)


def _run_dc_ac(netlist_text: str):
    """
    Run parse_netlist + dc_sweep + ac_sweep (same steps as run_pipeline steps 1-3).
    Returns (x, y, info, metrics, ac_metrics) — any may be None on failure.
    """
    from pipeline import parse_netlist, _extract_dc_metrics, _extract_ac_metrics, \
        _get_source_positive_node  # noqa: PLC0415
    from ngspice_runner import NgspiceRunner  # noqa: PLC0415

    netlist_text = _strip_control_blocks(netlist_text)

    try:
        info = parse_netlist(netlist_text)
    except Exception as e:
        print(f"    [WARN] parse_netlist failed: {e}")
        return None, None, None, None, None

    runner = NgspiceRunner()
    try:
        dc_results = runner.dc_sweep(netlist_text, {
            "sweep_var": info["signal_source"],
            "start": info.get("dc_start", 0),
            "stop": info.get("dc_stop", info["vdd"]),
            "step": info.get("dc_step", info["vdd"] / 100),
            "observe": [info["output_node"]],
        })
        x = np.array(dc_results[info["signal_source"]])
        y = np.array(dc_results[info["output_node"]])
    except Exception as e:
        print(f"    [WARN] dc_sweep failed: {e}")
        return None, None, info, None, None

    metrics = None
    try:
        from pipeline import _extract_dc_metrics  # noqa: PLC0415,F811
        metrics = _extract_dc_metrics(x, y, info["vdd"])
    except Exception as e:
        print(f"    [WARN] _extract_dc_metrics failed: {e}")

    ac_metrics = None
    try:
        pos_node = _get_source_positive_node(netlist_text, info["signal_source"])
        ac_results = runner.ac_sweep(netlist_text, {
            "sweep_type": "dec",
            "n_points": 20,
            "start_freq": 1e3,
            "stop_freq": 10e9,
            "input_node": pos_node,
            "output_nodes": [info["output_node"]],
        })
        ac_metrics = _extract_ac_metrics(ac_results, info["output_node"])
    except Exception as e:
        print(f"    [WARN] ac_sweep failed (continuing without AC data): {e}")

    return x, y, info, metrics, ac_metrics


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 3 — Individual tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── Test 1a: AI pipeline ──────────────────────────────────────────────────────

def test1_ai(netlist_text: str, output_dir: Path, caps: dict) -> dict:
    """Run the AI pipeline. Returns result dict."""
    if not caps["ai_agent"]:
        return _skipped("AI agent not available (no Ollama, no ANTHROPIC_API_KEY)")
    try:
        from pipeline import run_pipeline  # noqa: PLC0415
        va_path, nrmse = run_pipeline(netlist_text, output_dir=str(output_dir / "ai"))
        va_code = va_path.read_text()
        # run_pipeline already computed NRMSE internally — use it if valid
        if nrmse is not None:
            score_str = f"{nrmse:.4f}"
        else:
            # dynamic model or no data; re-score here so we always show something
            x, y, info, _, _ = _run_dc_ac(netlist_text)
            if x is not None and info is not None:
                score_str = _score(va_code, x, y, info["output_node"])
            else:
                score_str = "N/A (no DC data)"
        return {"va_code": va_code, "nrmse_str": score_str, "va_path": va_path}
    except Exception as e:
        return _failed(e)


# ── Test 1b: Non-AI pipeline ──────────────────────────────────────────────────

def test1_nonai(netlist_text: str, output_dir: Path, caps: dict,
                x, y, info) -> dict:
    """Run the non-AI numeric-fitting pipeline. Returns result dict."""
    if not caps["nonai_pipeline"]:
        return _skipped("non-AI pipeline not available (pipeline_ext import failed)")
    if not caps["ngspice"]:
        return _skipped("ngspice not found")

    nonai_mod = caps["_nonai_mod"]
    out = output_dir / "nonai"
    out.mkdir(parents=True, exist_ok=True)

    try:
        saved_files = nonai_mod.spice_to_verilog_ams(netlist_text, str(out))
    except Exception as e:
        return _failed(e)

    va_files = [f for f in saved_files if str(f).endswith(".va")]
    if not va_files:
        return _failed("non-AI pipeline produced no .va files")

    # Score each module; report best (lowest numeric NRMSE)
    results = []
    for va_path in va_files:
        va_code = Path(va_path).read_text()
        if x is not None and info is not None:
            score_str = _score(va_code, x, y, info["output_node"])
        else:
            score_str = "N/A (no DC data)"
        results.append({"va_code": va_code, "nrmse_str": score_str, "va_path": va_path})

    # Pick best scoreable result
    best = _pick_best(results)
    best["all_modules"] = results
    return best


# ── Test 2: Warm-start (non-AI baseline → AI refinement) ─────────────────────

def test2_warmstart(netlist_text: str, output_dir: Path, caps: dict,
                    nonai_va: str, x, y, info, metrics, ac_metrics) -> dict:
    """
    Pass the non-AI VA as baseline context to the AI prompt.
    The AI sees the numerically-fitted model and can correct/improve it.
    """
    if not caps["ai_agent"]:
        return _skipped("AI agent not available")
    if nonai_va is None:
        return _skipped("non-AI VA not available (Test 1b was skipped or failed)")
    if x is None or info is None:
        return _skipped("no DC sweep data available")

    try:
        from ai_agent import create_agent, generate, compute_nrmse, \
            evaluate_va_code, _is_dynamic_model  # noqa: PLC0415

        agent = create_agent()
        print("      [warm-start] calling AI with non-AI baseline...")
        va_code = generate(agent, netlist_text, x, y, info,
                           metrics=metrics, ac_metrics=ac_metrics,
                           baseline_va=nonai_va)
        score_str = _score(va_code, x, y, info["output_node"])

        out = output_dir / "warmstart"
        out.mkdir(parents=True, exist_ok=True)
        va_path = out / "model.va"
        va_path.write_text(va_code)
        return {"va_code": va_code, "nrmse_str": score_str, "va_path": va_path}
    except Exception as e:
        return _failed(e)


# ── Test 3: AI judge ───────────────────────────────────────────────────────────

_JUDGE_SYSTEM = (
    "You are an expert analog IC designer and Verilog-AMS specialist. "
    "You will be given two Verilog-AMS behavioral models for the same SPICE circuit, "
    "along with the circuit's DC sweep waveform data. "
    "Your job: produce the single best Verilog-AMS module. "
    "You may pick one of the two models, merge the best parts of both, or rewrite "
    "entirely if both have fundamental errors. "
    "Return ONLY the Verilog-AMS code — no explanation, no markdown fences."
)

def test3_judge(netlist_text: str, output_dir: Path, caps: dict,
                va_ai: str | None, va_nonai: str | None,
                x, y, info, metrics, ac_metrics) -> dict:
    """
    Send both VA codes to Claude as a judge. Claude returns the best merged model.
    Requires anthropic package + ANTHROPIC_API_KEY (Ollama lacks instruction-following
    reliability for structured judge tasks).
    """
    if not caps["anthropic_pkg"]:
        return _skipped(
            "anthropic Python package not installed "
            "(pip install anthropic + set ANTHROPIC_API_KEY)"
        )
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return _skipped("ANTHROPIC_API_KEY not set — AI judge requires Claude API")
    if va_ai is None and va_nonai is None:
        return _skipped("both VA inputs are None — nothing to judge")
    if x is None or info is None:
        return _skipped("no DC sweep data available")

    # Build judge prompt
    lines = [
        "## SPICE Netlist",
        netlist_text.strip(),
        "",
        "## DC Sweep Data",
        f"{'Input (V)':>10}  {'Output (V)':>10}",
        "─" * 24,
    ]
    idx = np.round(np.linspace(0, len(x) - 1, min(20, len(x)))).astype(int)
    for i in idx:
        lines.append(f"{x[i]:>10.4f}  {y[i]:>10.4f}")

    if metrics:
        lines += [
            "",
            "## DC Metrics",
            f"  VOH={metrics['voh']:.4f}V  VOL={metrics['vol']:.4f}V  "
            f"Vth={metrics['vth']:.4f}V  Gain={metrics['gain']:.2f}V/V",
        ]

    if va_ai:
        lines += ["", "## Model A — AI pipeline", va_ai.strip()]
    else:
        lines += ["", "## Model A — AI pipeline", "(not available)"]

    if va_nonai:
        lines += ["", "## Model B — Non-AI numeric-fitting pipeline", va_nonai.strip()]
    else:
        lines += ["", "## Model B — Non-AI pipeline", "(not available)"]

    lines += [
        "",
        "Return the single best Verilog-AMS module (no markdown, no explanation).",
    ]
    judge_prompt = "\n".join(lines)

    try:
        import anthropic  # noqa: PLC0415
        from ai_agent import clean_code  # noqa: PLC0415

        client = anthropic.Anthropic()
        print("      [judge] calling Claude claude-sonnet-4-6...", end="", flush=True)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": judge_prompt}],
        )
        print(" done")
        va_code = clean_code(msg.content[0].text)
        score_str = _score(va_code, x, y, info["output_node"])

        out = output_dir / "judge"
        out.mkdir(parents=True, exist_ok=True)
        va_path = out / "model.va"
        va_path.write_text(va_code)
        return {"va_code": va_code, "nrmse_str": score_str, "va_path": va_path}
    except Exception as e:
        return _failed(e)


# ── Test 4: OSDI validation ───────────────────────────────────────────────────

_OSDI_TESTBENCH_TEMPLATE = """\
* OSDI equivalence testbench for {module_name}
* Compares: SPICE golden vs Verilog-AMS compiled model

.title OSDI validation — {module_name}

* Load the compiled Verilog-AMS model
.osdi {osdi_path}

* ── Golden SPICE circuit ────────────────────────────────────────────
{netlist_body}

* ── Behavioral model under test ────────────────────────────────────
X_model {signal_source} {output_node}_model {module_name}

* ── DC sweep ────────────────────────────────────────────────────────
.DC {signal_source} {dc_start} {dc_stop} {dc_step}
.PRINT DC v({output_node}) v({output_node}_model)

.END
"""

def test4_osdi(netlist_text: str, output_dir: Path, caps: dict,
               va_code: str, x, y, info) -> dict:
    """
    Compile the best VA model with OpenVAF → .osdi, then simulate both the
    original SPICE circuit and the behavioral model in the same ngspice run,
    and compute NRMSE from the actual simulation outputs.

    This is the ground-truth evaluation — Test 1-3 use a Python proxy.
    """
    if not caps["openvaf"]:
        return _skipped(
            "OpenVAF not installed. "
            "No pre-built macOS ARM64 binary exists. "
            "To build: install Rust (curl https://sh.rustup.rs | sh), "
            "then: cargo install --git https://github.com/pascalkuthe/OpenVAF "
            "(requires LLVM 14+: brew install llvm). "
            "Also needs ngspice compiled with --enable-osdi."
        )
    if not caps["ngspice_osdi"]:
        return _skipped(
            "ngspice not compiled with --enable-osdi. "
            "The Homebrew bottle lacks this flag. "
            "Fix: brew uninstall ngspice && compile from source with "
            "./configure --enable-osdi --enable-xspice --enable-cider"
        )
    if va_code is None:
        return _skipped("no VA code available to compile")
    if x is None or info is None:
        return _skipped("no DC sweep data for comparison")

    out = output_dir / "osdi"
    out.mkdir(parents=True, exist_ok=True)

    # Write VA file
    va_path = out / "model.va"
    va_path.write_text(va_code)

    # Extract module name from VA
    import re
    m = re.search(r"\bmodule\s+(\w+)", va_code)
    module_name = m.group(1) if m else "BEHAVIORAL_MODEL"

    # Compile with OpenVAF
    osdi_path = out / "model.osdi"
    print(f"      [osdi] compiling {va_path.name} with OpenVAF...", end="", flush=True)
    result = subprocess.run(
        ["openvaf", str(va_path), "-o", str(osdi_path)],
        capture_output=True, text=True, cwd=str(out)
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip()
        print(" FAILED")
        return _failed(f"OpenVAF compilation error:\n{msg}")
    print(" done")

    # Build testbench
    # Strip .DC and .END from the original netlist body for embedding
    netlist_lines = []
    for line in netlist_text.splitlines():
        stripped = line.strip().upper()
        if stripped.startswith(".DC") or stripped == ".END":
            continue
        netlist_lines.append(line)
    netlist_body = "\n".join(netlist_lines)

    x_range = x[-1] - x[0]
    dc_step = x_range / max(len(x) - 1, 1)
    testbench = _OSDI_TESTBENCH_TEMPLATE.format(
        module_name=module_name,
        osdi_path=str(osdi_path),
        netlist_body=netlist_body,
        signal_source=info["signal_source"],
        output_node=info["output_node"],
        dc_start=f"{x[0]:.4f}",
        dc_stop=f"{x[-1]:.4f}",
        dc_step=f"{dc_step:.6f}",
    )

    tb_path = out / "testbench.sp"
    tb_path.write_text(testbench)

    # Run ngspice
    print(f"      [osdi] running ngspice testbench...", end="", flush=True)
    ng_result = subprocess.run(
        ["ngspice", "-b", str(tb_path)],
        capture_output=True, text=True
    )
    if ng_result.returncode != 0:
        print(" FAILED")
        return _failed(f"ngspice failed:\n{ng_result.stderr[:500]}")
    print(" done")

    # Parse ngspice output — look for SPICE vs model columns
    spice_vals, model_vals = [], []
    for line in ng_result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                spice_vals.append(float(parts[1]))
                model_vals.append(float(parts[2]))
            except ValueError:
                continue

    if not spice_vals:
        return _failed("could not parse ngspice output — no numeric rows found")

    from ai_agent import compute_nrmse  # noqa: PLC0415
    y_spice = np.array(spice_vals)
    y_model = np.array(model_vals)
    nrmse = compute_nrmse(y_spice, y_model)

    return {
        "va_code": va_code,
        "nrmse_str": f"{nrmse:.4f} (OSDI/ngspice — ground truth)",
        "nrmse_float": nrmse,
        "va_path": va_path,
        "osdi_path": osdi_path,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 4 — Result helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _skipped(reason: str) -> dict:
    return {"skipped": True, "reason": reason, "va_code": None, "nrmse_str": "—"}


def _failed(exc) -> dict:
    return {"failed": True, "error": str(exc), "va_code": None, "nrmse_str": "ERROR"}


def _pick_best(results: list) -> dict:
    """From a list of result dicts, return the one with lowest numeric NRMSE."""
    best = results[0]
    best_val = float("inf")
    for r in results:
        s = r.get("nrmse_str", "")
        try:
            v = float(s.split()[0])
            if v < best_val:
                best_val = v
                best = r
        except (ValueError, IndexError):
            continue
    return best


def _nrmse_float(result: dict) -> float:
    """Extract numeric NRMSE from result dict, or inf if not available."""
    s = result.get("nrmse_str", "")
    try:
        return float(s.split()[0])
    except (ValueError, IndexError):
        return float("inf")


def _status(result: dict) -> str:
    if result.get("skipped"):
        return f"SKIPPED  ({result['reason']})"
    if result.get("failed"):
        return f"FAILED   ({result['error'][:80]})"
    return result.get("nrmse_str", "?")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 5 — Per-netlist orchestration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_comparison(netlist_path: Path, caps: dict, args) -> dict:
    """Run all four tests on one netlist. Returns summary dict."""
    name = netlist_path.stem
    print(f"\n{'━' * 68}")
    print(f"  NETLIST: {netlist_path.name}")
    print(f"{'━' * 68}")

    netlist_text = _load_netlist(netlist_path)

    with tempfile.TemporaryDirectory(prefix=f"synapticams_{name}_") as tmpdir:
        out = Path(tmpdir)

        # Shared DC/AC data (all tests use same sweep)
        print("\n[Shared] Running DC + AC sweep...")
        x, y, info, metrics, ac_metrics = _run_dc_ac(netlist_text)
        if x is not None:
            print(f"  DC: {len(x)} points  ({x[0]:.3f}V → {x[-1]:.3f}V)")
        else:
            print("  [WARN] DC sweep failed — score-based tests may be limited")

        results = {}

        # ── Test 1a: AI ────────────────────────────────────────────────────
        if not args.skip_ai:
            print("\n[Test 1a] AI pipeline...")
            results["ai"] = test1_ai(netlist_text, out, caps)
            print(f"  Result: {_status(results['ai'])}")
        else:
            results["ai"] = _skipped("--skip-ai flag set")

        # ── Test 1b: Non-AI ────────────────────────────────────────────────
        if not args.skip_nonai:
            print("\n[Test 1b] Non-AI numeric-fitting pipeline...")
            results["nonai"] = test1_nonai(netlist_text, out, caps, x, y, info)
            print(f"  Result: {_status(results['nonai'])}")
            # If multiple modules, show all
            for mod in results["nonai"].get("all_modules", [])[1:]:
                print(f"         module: {_status(mod)}")
        else:
            results["nonai"] = _skipped("--skip-nonai flag set")

        # ── Test 2: Warm-start ─────────────────────────────────────────────
        if not args.skip_ai and not args.skip_nonai:
            print("\n[Test 2] Warm-start (non-AI → AI)...")
            nonai_va = results["nonai"].get("va_code")
            results["warmstart"] = test2_warmstart(
                netlist_text, out, caps,
                nonai_va, x, y, info, metrics, ac_metrics
            )
            print(f"  Result: {_status(results['warmstart'])}")
        else:
            results["warmstart"] = _skipped("requires both AI and non-AI (flags set)")

        # ── Test 3: AI judge ───────────────────────────────────────────────
        if not args.skip_judge:
            print("\n[Test 3] AI judge (Claude merges both models)...")
            results["judge"] = test3_judge(
                netlist_text, out, caps,
                results["ai"].get("va_code"),
                results["nonai"].get("va_code"),
                x, y, info, metrics, ac_metrics
            )
            print(f"  Result: {_status(results['judge'])}")
        else:
            results["judge"] = _skipped("--skip-judge flag set")

        # ── Test 4: OSDI (uses best VA from tests 1-3) ─────────────────────
        print("\n[Test 4] OSDI validation (ground-truth ngspice comparison)...")
        # Pick the best VA from tests 1-3 to validate
        candidates = [results[k] for k in ("ai", "nonai", "warmstart", "judge")
                      if not results[k].get("skipped") and not results[k].get("failed")
                      and results[k].get("va_code")]
        best_va = _pick_best(candidates).get("va_code") if candidates else None
        results["osdi"] = test4_osdi(netlist_text, out, caps, best_va, x, y, info)
        print(f"  Result: {_status(results['osdi'])}")

        # ── Per-netlist summary ────────────────────────────────────────────
        print(f"\n{'─' * 68}")
        print(f"  SUMMARY — {name}")
        print(f"{'─' * 68}")
        rows = [
            ("Test 1a  AI pipeline",              results["ai"]),
            ("Test 1b  Non-AI (best module)",      results["nonai"]),
            ("Test 2   Warm-start (non-AI→AI)",   results["warmstart"]),
            ("Test 3   AI judge (merged)",         results["judge"]),
            ("Test 4   OSDI ground-truth",         results["osdi"]),
        ]
        winner = None
        winner_score = float("inf")
        for label, r in rows:
            s = _status(r)
            print(f"  {label:<40} {s}")
            score = _nrmse_float(r)
            if score < winner_score:
                winner_score = score
                winner = label

        if winner and winner_score < float("inf"):
            print(f"\n  WINNER (lowest NRMSE): {winner}  ({winner_score:.4f})")
        else:
            print("\n  WINNER: undetermined (no numeric scores available)")

        return {
            "name": name,
            "results": results,
            "winner": winner,
            "winner_score": winner_score,
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SECTION 6 — Main
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--netlist", help="Run on a single netlist (default: all in examples/netlists/)")
    parser.add_argument("--skip-ai",    action="store_true", help="Skip AI pipeline (Tests 1a, 2, 3)")
    parser.add_argument("--skip-nonai", action="store_true", help="Skip non-AI pipeline (Tests 1b, 2)")
    parser.add_argument("--skip-judge", action="store_true", help="Skip AI judge (Test 3)")
    args = parser.parse_args()

    caps = detect_capabilities()

    # Collect netlists
    if args.netlist:
        netlists = [Path(args.netlist)]
    else:
        netlist_dir = REPO_ROOT / "examples" / "netlists"
        # Exclude VCO — needs run_vco_pipeline, not run_pipeline
        netlists = sorted(
            p for p in netlist_dir.glob("*.cir")
            if p.stem not in ("vco_ring5",)
        )

    print(f"\nNetlists to process: {[p.name for p in netlists]}")

    all_summaries = []
    for nlp in netlists:
        summary = run_comparison(nlp, caps, args)
        all_summaries.append(summary)

    # ── Final cross-netlist summary ────────────────────────────────────────
    print(f"\n{'=' * 68}")
    print(" FINAL CROSS-NETLIST SUMMARY")
    print(f"{'=' * 68}")
    tests = ["ai", "nonai", "warmstart", "judge", "osdi"]
    labels = ["AI", "NonAI", "WarmStart", "Judge", "OSDI"]

    header = f"  {'Netlist':<28} " + "  ".join(f"{l:<16}" for l in labels)
    print(header)
    print("  " + "─" * (len(header) - 2))
    for s in all_summaries:
        row = f"  {s['name']:<28} "
        for t in tests:
            r = s["results"].get(t, {})
            cell = _status(r)[:16]
            row += f"  {cell:<16}"
        print(row)

    print(f"\n{'=' * 68}")
    print(" All tests complete.")
    skipped_any = any(
        s["results"].get(t, {}).get("skipped")
        for s in all_summaries for t in tests
    )
    if skipped_any:
        print(" [!] Some tests were skipped — see CAPABILITY CHECK output above for fixes.")
    print(f"{'=' * 68}\n")


if __name__ == "__main__":
    main()
