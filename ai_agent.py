#!/usr/bin/env python3
"""
ai_agent.py — LLM integration for Verilog-AMS generation

Backends (auto-detected in priority order):
  1. Anthropic Claude  — set ANTHROPIC_API_KEY
  2. Ollama (local)    — run: ollama serve && ollama pull qwen2.5-coder:7b
"""

import os
import re
import json
import numpy as np


# ── System prompt ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert analog circuit engineer specializing in Verilog-AMS behavioral modeling.
Generate a Verilog-AMS (.va) file that replicates a circuit's transfer characteristic.

## Syntax rules
- First line MUST be: `include "disciplines.vams"
- When using laplace_nd or tau, also add: `include "constants.vams"
- Module declaration ends with semicolon: module NAME (out, in);
- Port declarations: electrical out, in;
- Parameters: parameter real name = value;
- Contribution: V(out) <+ expression;
- Always clamp to rails: V(out) <+ min(voh, max(vol, expression));
- No markdown fences — return pure .va code only

## Example 1 — static model (no bandwidth data)

`include "disciplines.vams"
module DIFF_AMP (out, in);
  electrical out, in;
  parameter real voh  = 1.8;
  parameter real vol  = 0.2;
  parameter real vth  = 0.9;
  parameter real gain = 8.0;
  analog begin
    V(out) <+ min(voh, max(vol, (voh+vol)/2.0 + gain * (V(in) - vth)));
  end
endmodule

## Example 2 — dynamic model (when bandwidth / tau is provided)

`include "disciplines.vams"
`include "constants.vams"
module CML_RX (out, in);
  electrical out, in;
  parameter real voh  = 1.8;
  parameter real vol  = 1.0;
  parameter real vth  = 0.9;
  parameter real gain = 5.07;
  parameter real tau  = 7.96e-10;
  analog begin
    V(out) <+ min(voh, max(vol, (voh+vol)/2.0 + gain * laplace_nd(V(in) - vth, {1.0}, {1.0, tau})));
  end
endmodule

laplace_nd(signal, {num}, {den}) models H(s)=N(s)/D(s).
For a first-order lowpass H(s)=1/(1+s*tau): use num={1.0}, den={1.0, tau}.
(V(in) - vth) centres amplification on the correct bias point — never omit it."""


# ── Prompt builders ────────────────────────────────────────────────────

def _build_prompt(netlist, x, y, info, metrics=None, ac_metrics=None, baseline_va=None):
    import math as _math

    lines = [
        "Generate a Verilog-AMS behavioral model for the circuit below.",
        "",
        "## SPICE Netlist",
        netlist.strip(),
        "",
    ]

    # DC sweep data table
    if x is not None and y is not None:
        lines += [
            f"## ngspice DC Sweep  "
            f"({info['signal_source']} swept, {info['output_node']} observed)",
            f"{'Input (V)':>10}  {'Output (V)':>10}",
            "─" * 24,
        ]
        idx = np.round(np.linspace(0, len(x) - 1, min(20, len(x)))).astype(int)
        for i in idx:
            lines.append(f"{x[i]:>10.4f}  {y[i]:>10.4f}")

    # DC metrics
    if metrics is not None:
        lines += [
            "",
            "## Key DC Behavioral Metrics",
            f"  VOH  (output-high voltage) = {metrics['voh']:.4f} V",
            f"  VOL  (output-low  voltage) = {metrics['vol']:.4f} V",
            f"  Vth  (input threshold)     = {metrics['vth']:.4f} V",
            f"  Gain (peak |dVout/dVin|)   = {metrics['gain']:.2f} V/V",
        ]

    # AC Bode data
    if ac_metrics is not None:
        freqs  = ac_metrics['frequencies']
        mag_db = ac_metrics['magnitude_db']
        phases = ac_metrics['phase']
        lines += [
            "",
            "## AC Frequency Response  (small-signal, linearised at DC bias)",
            f"{'Frequency (Hz)':>16}  {'Gain (dB)':>10}  {'Phase (°)':>10}",
            "─" * 42,
        ]
        idx_ac = np.round(
            np.linspace(0, len(freqs) - 1, min(20, len(freqs)))
        ).astype(int)
        for i in idx_ac:
            lines.append(
                f"{float(freqs[i]):>16.3e}  "
                f"{float(mag_db[i]):>10.2f}  "
                f"{float(phases[i]):>10.1f}"
            )
        lines += [
            "",
            f"  DC gain = {ac_metrics['dc_gain_db']:.2f} dB"
            f"  ({ac_metrics['dc_gain_linear']:.1f} V/V)",
        ]
        if ac_metrics.get('bw_3db_hz'):
            tau = 1.0 / (2.0 * _math.pi * ac_metrics['bw_3db_hz'])
            lines += [
                f"  -3dB BW = {ac_metrics['bw_3db_hz'] / 1e6:.3f} MHz",
                f"  tau     = {tau * 1e9:.4f} ns",
            ]

    # ── Pre-filled skeleton ──────────────────────────────────────────────
    # When we have simulation-derived parameters, give the LLM a skeleton
    # with every parameter pre-computed.  It only needs to write the single
    # V(out) contribution line — reducing failure surface dramatically.
    if metrics is not None:
        voh  = metrics['voh']
        vol  = metrics['vol']
        vth  = metrics['vth']
        gain = metrics['gain']

        tau_val = None
        if ac_metrics is not None and ac_metrics.get('bw_3db_hz'):
            tau_val = 1.0 / (2.0 * _math.pi * ac_metrics['bw_3db_hz'])

        has_tau = tau_val is not None
        vmid    = (voh + vol) / 2.0

        skel = [
            "",
            "## Pre-filled skeleton — complete the V(out) line inside analog begin",
            "",
            '`include "disciplines.vams"',
        ]
        if has_tau:
            skel.append('`include "constants.vams"')
        skel += [
            "module BEHAVIORAL_MODEL (out, in);",
            "  electrical out, in;",
            f"  parameter real voh  = {voh:.4f};   // output high rail",
            f"  parameter real vol  = {vol:.4f};   // output low rail",
            f"  parameter real vth  = {vth:.4f};   // input threshold",
            f"  parameter real gain = {gain:.4f};  // peak small-signal gain (V/V)",
        ]
        if has_tau:
            skel.append(
                f"  parameter real tau  = {tau_val:.4e};  "
                f"// time constant = 1/(2π×{ac_metrics['bw_3db_hz']/1e6:.1f}MHz)"
            )
        skel += [
            "  analog begin",
            "    // Fill in exactly one line:",
        ]
        if has_tau:
            skel += [
                f"    //   vmid = {vmid:.4f} = (voh+vol)/2",
                "    V(out) <+ min(voh, max(vol, (voh+vol)/2.0"
                " + gain * laplace_nd(V(in) - vth, {1.0}, {1.0, tau})));",
            ]
        else:
            skel += [
                f"    //   vmid = {vmid:.4f} = (voh+vol)/2",
                "    V(out) <+ min(voh, max(vol, (voh+vol)/2.0"
                " + gain * (V(in) - vth)));",
            ]
        skel += [
            "  end",
            "endmodule",
            "",
            "Return the complete module above with the V(out) line confirmed or corrected.",
        ]
        lines += skel
    else:
        lines += [
            "",
            f"Signal input: source={info['signal_source']}, "
            f"output node='{info['output_node']}', VDD={info['vdd']} V",
            "",
            "Generate the Verilog-AMS module:",
        ]

    if baseline_va is not None:
        lines += [
            "",
            "## Numerically-Fitted Baseline Model (from non-AI pipeline)",
            "A numeric curve-fitting pipeline has already generated the following",
            "Verilog-AMS model. Use it as a starting point: keep the structure if",
            "it is correct, but fix any inaccuracies you can identify from the",
            "sweep data and metrics above.",
            "",
            baseline_va.strip(),
        ]

    return "\n".join(lines)


def _build_refine_prompt(netlist, x, y, info, current_code, nrmse):
    y_model = evaluate_va_code(current_code, x, info["output_node"])
    valid   = ~np.isnan(y_model)
    if np.any(valid):
        errors = np.abs(y[valid] - y_model[valid])
        worst  = np.argsort(errors)[-5:][::-1]
        xv, yv, ymv = x[valid], y[valid], y_model[valid]
        worst_lines = [
            f"  in={xv[i]:.4f} V  spice={yv[i]:.4f} V  model={ymv[i]:.4f} V"
            for i in worst
        ]
    else:
        worst_lines = ["  (model returned all NaN — check analog expression syntax)"]
    return "\n".join([
        f"The previous model had NRMSE={nrmse:.4f} (target < 0.05).",
        "Worst-error points:",
        *worst_lines,
        "",
        "Previous model:",
        current_code,
        "",
        "Fix the model to reduce these errors. Return only corrected .va code:",
    ])


# ── NRMSE ──────────────────────────────────────────────────────────────

def compute_nrmse(y_true, y_pred):
    """
    Normalized RMS error relative to the output voltage range.
    Returns inf if y_pred is all NaN, 0.0 if output is flat.
    """
    valid = ~np.isnan(y_pred)
    if not np.any(valid):
        return float("inf")
    y_range = float(y_true.max() - y_true.min())
    if y_range < 1e-10:
        return 0.0
    rmse = np.sqrt(np.mean((y_true[valid] - y_pred[valid]) ** 2))
    return float(rmse / y_range)


# ── Verilog-AMS evaluator ──────────────────────────────────────────────

def evaluate_va_code(va_code, x, output_node):
    """
    Numerically evaluate a Verilog-AMS module at each x value.

    Supports:
      - Single V(out) <+ expression;
      - if/else with a V(in) threshold condition

    Returns np.array of y values (NaN where evaluation fails).
    """
    y = np.full(len(x), np.nan)

    # Extract `parameter real name = value;` — two passes so expressions
    # like `parameter real vmid = (voh + vol) / 2.0;` work after voh/vol
    # are already known.
    params = {}
    param_exprs = {}   # name → raw expression string, for second pass
    for m in re.finditer(r"parameter\s+real\s+(\w+)\s*=\s*([^;,\n]+)", va_code):
        name, expr_str = m.group(1), m.group(2).strip()
        try:
            params[name] = float(expr_str)
        except ValueError:
            param_exprs[name] = expr_str   # deferred — needs other params

    # Second pass: evaluate deferred parameter expressions with known params
    def _try_eval_expr(expr_str, known):
        e = expr_str
        for pname, pval in known.items():
            e = re.sub(r'\b' + re.escape(pname) + r'\b', str(pval), e)
        try:
            return float(eval(e, {"__builtins__": {}}))  # noqa: S307
        except Exception:
            return None

    for name, expr_str in param_exprs.items():
        v = _try_eval_expr(expr_str, params)
        if v is not None:
            params[name] = v

    # Also extract analog/initial-block variable assignments: `name = expr;`
    for m in re.finditer(r"^\s*(\w+)\s*=\s*([^;]+);", va_code, re.M):
        name, expr_str = m.group(1), m.group(2).strip()
        if name in params:
            continue   # parameter real takes precedence
        v = _try_eval_expr(expr_str, params)
        if v is not None:
            params[name] = v

    # Extract input port names so bare references (e.g. `in`) can be
    # mapped to x_val in addition to the V(port) form.
    input_ports = re.findall(
        r"(?:input|inout)\s+electrical\s+(\w+)", va_code
    )

    def _to_py(expr):
        """Translate a Verilog-AMS expression to a Python-evaluable string."""
        # DC substitution for laplace_nd: at s=0, H(s) = num[0]/den[0] = 1/1 = 1
        # so laplace_nd(signal, {1.0}, {1.0, tau}) → signal.
        # This lets evaluate_va_code compute a meaningful DC NRMSE for dynamic models.
        # DC substitution for laplace_nd: replace with inner signal wrapped in parens.
        # Pattern includes the closing ')' so nothing is left dangling.
        # gain * laplace_nd(V(in) - vth, {1.0}, {1.0, tau}) → gain * (V(in) - vth)
        expr = re.sub(
            r"laplace_nd\s*\(([^,]+),\s*\{[^}]+\},\s*\{[^}]+\}\s*\)",
            r"(\1)", expr,
        )
        expr = re.sub(r"\bV\s*\([^)]+\)", "x_val", expr)
        # Also replace bare port names (e.g. `in` without V()) → x_val.
        # LLMs sometimes write laplace_nd(in - vth, ...) omitting V().
        for port in input_ports:
            expr = re.sub(r"\b" + re.escape(port) + r"\b", "x_val", expr)
        expr = re.sub(r"\btanh\b",    "np.tanh",    expr)
        expr = re.sub(r"\bexp\b",     "np.exp",     expr)
        expr = re.sub(r"\bsqrt\b",    "np.sqrt",    expr)
        expr = re.sub(r"\babs\b",     "np.abs",     expr)
        expr = re.sub(r"\bmax\b",     "np.maximum", expr)
        expr = re.sub(r"\bmin\b",     "np.minimum", expr)
        for name, val in params.items():
            expr = re.sub(r"\b" + re.escape(name) + r"\b", str(val), expr)
        return expr

    def _eval(expr, x_val):
        try:
            return float(eval(expr, {"np": np, "x_val": x_val}))  # noqa: S307
        except Exception:
            return np.nan

    # Try if/else pattern first (most MOSFET models use threshold regions)
    if_m = re.search(
        r"if\s*\(\s*V\s*\([^)]+\)\s*([<>]=?)\s*([^)]+)\)"
        r"\s*(?:begin)?\s*(.*?)(?:end)?\s*else\s*(?:begin)?\s*(.*?)(?:end)?(?=\s*end\b|\Z)",
        va_code, re.DOTALL,
    )
    if if_m:
        op, thresh_str    = if_m.group(1), if_m.group(2).strip()
        then_block        = if_m.group(3)
        else_block        = if_m.group(4)
        then_assigns      = re.findall(r"V\s*\([^)]+\)\s*<\+\s*([^;]+)", then_block)
        else_assigns      = re.findall(r"V\s*\([^)]+\)\s*<\+\s*([^;]+)", else_block)
        try:
            threshold = float(eval(_to_py(thresh_str), {"np": np}))  # noqa: S307
        except Exception:
            threshold = None
        if then_assigns and else_assigns and threshold is not None:
            then_expr = _to_py(then_assigns[-1])
            else_expr = _to_py(else_assigns[-1])
            ops = {
                "<":  lambda a, b: a <  b,
                "<=": lambda a, b: a <= b,
                ">":  lambda a, b: a >  b,
                ">=": lambda a, b: a >= b,
            }
            cmp = ops.get(op, lambda a, b: a < b)
            for i, xv in enumerate(x):
                expr = then_expr if cmp(xv, threshold) else else_expr
                y[i] = _eval(expr, xv)
            return y

    # Fallback: use the last V(out) <+ assignment (single-expression models)
    assigns = re.findall(r"V\s*\([^)]+\)\s*<\+\s*([^;]+)", va_code)
    if assigns:
        expr = _to_py(assigns[-1])
        for i, xv in enumerate(x):
            y[i] = _eval(expr, xv)

    return y


def clean_code(text):
    """Strip markdown fences and fix common Ollama Verilog-AMS syntax errors."""
    text = re.sub(r"```(?:verilog(?:-ams)?|vams)?\n?", "", text, flags=re.I)
    text = text.strip()

    # Strip everything before the first valid Verilog-AMS token (`include or module)
    # LLMs often add preamble like "Here is a Verilog-AMS model:"
    first_valid = re.search(r'(`include|module)\b', text)
    if first_valid:
        text = text[first_valid.start():]

    # Strip everything after endmodule (LLMs often add explanations)
    endmodule_match = re.search(r'\bendmodule\b', text)
    if endmodule_match:
        text = text[:endmodule_match.end()].strip()

    # Fix missing backtick before `include (e.g. include "disciplines.vams")
    text = re.sub(r'^(\s*)include\s+"', r'\1`include "', text, flags=re.M)
    # Fix module declaration missing semicolon (e.g. module foo(out, in)\n)
    text = re.sub(r'(module\s+\w+\s*\([^)]*\))\s*\n', r'\1;\n', text)
    # Fix module-level `real name = val;` → `parameter real name = val;`
    # Only apply before `analog begin` block
    analog_idx = text.find('analog begin')
    if analog_idx > 0:
        pre = text[:analog_idx]
        post = text[analog_idx:]
        pre = re.sub(r'^(\s*)real\s+(\w+)\s*=\s*', r'\1parameter real \2 = ', pre, flags=re.M)
        text = pre + post

    # Fix missing port directions for OpenVAF compatibility
    # OpenVAF requires explicit input/output declarations
    # Pattern: module foo(out, in); \n  electrical out, in;
    # Should add: input in; output out; after module declaration
    module_match = re.search(r'module\s+\w+\s*\(([^)]+)\)\s*;', text)
    if module_match:
        ports = [p.strip() for p in module_match.group(1).split(',')]
        # Find the electrical declaration line
        elec_match = re.search(r'(\s*)electrical\s+([^;]+);', text)
        if elec_match and ports:
            # Check if port directions already exist (to avoid duplicates)
            # Look for 'output <portname>;' or 'input <portname>;' before electrical declaration
            pre_electrical = text[:elec_match.start()]
            has_directions = any(
                re.search(rf'\b(input|output)\s+{re.escape(port)}\s*;', pre_electrical)
                for port in ports
            )

            if not has_directions:
                # Assume first port is output, rest are inputs (common convention)
                # This matches the typical pattern: module foo(out, in1, in2)
                indent = elec_match.group(1)
                directions = []
                if len(ports) > 0:
                    directions.append(f"output {ports[0]};")
                for port in ports[1:]:
                    directions.append(f"input {port};")

                # Insert direction declarations before electrical declaration
                direction_block = indent + f'\n{indent}'.join(directions) + '\n'
                text = text[:elec_match.start()] + direction_block + text[elec_match.start():]

    # Ensure `include "disciplines.vams" is always present at the beginning
    # OpenVAF requires this header for electrical net types
    if not re.search(r'`include\s+"disciplines\.vams"', text):
        # Check if there's already an `include "constants.vams"
        if re.search(r'`include\s+"constants\.vams"', text):
            # Insert disciplines.vams before constants.vams
            text = re.sub(
                r'(`include\s+"constants\.vams")',
                r'`include "disciplines.vams"\n\1',
                text,
                count=1
            )
        else:
            # Insert at the very beginning
            text = '`include "disciplines.vams"\n' + text

    return text


# ── Ollama backend ─────────────────────────────────────────────────────

class OllamaAgent:
    DEFAULT_MODEL = "deepseek-r1:32b"
    BASE_URL      = "http://192.168.1.34:11434"  # Remote Ollama server

    def __init__(self, model=None, base_url=None, timeout=180):
        self.model    = model    or self.DEFAULT_MODEL
        self.base_url = base_url or self.BASE_URL
        self.timeout  = timeout

    def chat(self, system, user):
        import urllib.request
        payload = json.dumps({
            "model":    self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())["message"]["content"]

    @classmethod
    def is_available(cls, base_url=BASE_URL):
        import urllib.request
        try:
            urllib.request.urlopen(f"{base_url}/api/tags", timeout=3)
            return True
        except Exception:
            return False

    @classmethod
    def available_models(cls, base_url=BASE_URL):
        import urllib.request
        try:
            with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3) as r:
                return [m["name"] for m in json.loads(r.read()).get("models", [])]
        except Exception:
            return []


# ── Claude backend ─────────────────────────────────────────────────────

class ClaudeAgent:
    DEFAULT_MODEL = "claude-opus-4-6"

    def __init__(self, model=None):
        self.model  = model or self.DEFAULT_MODEL
        import anthropic
        self.client = anthropic.Anthropic()

    def chat(self, system, user):
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text


# ── Factory ────────────────────────────────────────────────────────────

def create_agent(provider=None, model=None):
    """
    Create an AI agent.  Auto-detects backend if provider is None:
      - ANTHROPIC_API_KEY set → Claude
      - Ollama reachable      → Ollama (picks best available model)
    """
    use_claude = (
        provider == "anthropic"
        or (provider is None and os.environ.get("ANTHROPIC_API_KEY"))
    )
    if use_claude:
        return ClaudeAgent(model=model)

    if provider == "ollama" or OllamaAgent.is_available():
        if model is None:
            available = OllamaAgent.available_models()
            preferred = ["qwen2.5-coder", "codellama", "deepseek-coder", "llama3"]
            model = next(
                (a for p in preferred for a in available if a.startswith(p)),
                available[0] if available else OllamaAgent.DEFAULT_MODEL,
            )
        return OllamaAgent(model=model)

    raise RuntimeError(
        "No AI backend found.\n"
        "  Local:  ollama serve && ollama pull qwen2.5-coder:7b\n"
        "  Cloud:  export ANTHROPIC_API_KEY=sk-ant-..."
    )


# ── Public API ─────────────────────────────────────────────────────────

def generate(agent, netlist, x, y, info, metrics=None, ac_metrics=None, baseline_va=None):
    """Initial Verilog-AMS generation."""
    name = f"{type(agent).__name__}/{getattr(agent, 'model', '?')}"
    print(f"      [{name}] generating...", end="", flush=True)
    code = clean_code(agent.chat(
        SYSTEM_PROMPT,
        _build_prompt(netlist, x, y, info, metrics=metrics, ac_metrics=ac_metrics,
                      baseline_va=baseline_va),
    ))
    print(" done")
    return code


def refine(agent, netlist, x, y, info, current_code, nrmse):
    """Refine Verilog-AMS given the current NRMSE."""
    name = f"{type(agent).__name__}/{getattr(agent, 'model', '?')}"
    print(f"      [{name}] refining (NRMSE={nrmse:.4f})...", end="", flush=True)
    code = clean_code(agent.chat(
        SYSTEM_PROMPT,
        _build_refine_prompt(netlist, x, y, info, current_code, nrmse),
    ))
    print(" done")
    return code


# ── VCO Verilog-AMS generation (template-based, no LLM needed) ────────

def generate_vco_va(vco_metrics, module_name="VCO_RING5"):
    """
    Generate a Verilog-AMS behavioral model for a characterized ring VCO.

    Uses a deterministic template — no LLM call — because the VCO model
    structure is fixed: f_inst = f_ref + Kvco*(V(ctrl) - Vctrl_ref),
    phase integrated by idtmod, output as a sinusoid.

    Args:
        vco_metrics: dict returned by pipeline.vco_tran_sweep() or
                     pipeline._fit_vco_kvco().  Required keys:
                       kvco, f_ref, vctrl_ref, r_squared
        module_name: Verilog-AMS module name (default "VCO_RING5")

    Returns:
        str — complete Verilog-AMS source
    """
    kvco      = vco_metrics['kvco']
    f_ref     = vco_metrics['f_ref']
    vctrl_ref = vco_metrics['vctrl_ref']
    r2        = vco_metrics['r_squared']
    kvco_mhz  = kvco / 1e6
    f_ref_mhz = f_ref / 1e6

    return f"""\
`include "disciplines.vams"
`include "constants.vams"
// VCO behavioral model generated by SynapticAMS
// Source: ngspice .TRAN characterisation of 5-stage current-starved ring VCO
//
// Model:  f_inst = f_ref + Kvco * (V(ctrl) - Vctrl_ref)
//         V(out) = vbias + vamp * sin(2π * idtmod(f_inst, 0, 1, 0))
//
// Extracted parameters:
//   Kvco      = {kvco_mhz:.2f} MHz/V    (VCO gain, linear fit)
//   f_ref     = {f_ref_mhz:.2f} MHz     (frequency at Vctrl_ref)
//   Vctrl_ref = {vctrl_ref:.3f} V       (reference bias point)
//   R²        = {r2:.4f}               (linearity of Kvco fit)
//
// In a full PLL: Vctrl is driven by the charge-pump loop filter.
// The loop locks when f_inst = N * f_ref_input (N = divider ratio).
module {module_name} (out, ctrl);
  electrical out, ctrl;

  // ── Extracted VCO parameters ─────────────────────────────────
  parameter real Kvco      = {kvco:.6e};   // Hz/V
  parameter real f_ref     = {f_ref:.6e};  // Hz @ Vctrl_ref
  parameter real vctrl_ref = {vctrl_ref:.4f};   // V

  // ── Output signal parameters ─────────────────────────────────
  parameter real vamp  = 0.9;   // output amplitude (V, half-swing around vbias)
  parameter real vbias = 0.9;   // output DC bias (V)

  real f_inst;

  analog begin
    // Instantaneous frequency (linear Kvco model)
    f_inst = f_ref + Kvco * (V(ctrl) - vctrl_ref);
    // Clamp to 1 MHz minimum — prevents negative frequency if Vctrl undershoots
    if (f_inst < 1.0e6) f_inst = 1.0e6;
    // idtmod integrates f_inst to produce phase (0→1 = one full cycle)
    // sin converts phase to output voltage
    V(out) <+ vbias + vamp * sin(2.0 * `M_PI * idtmod(f_inst, 0.0, 1.0, 0.0));
  end
endmodule
"""
