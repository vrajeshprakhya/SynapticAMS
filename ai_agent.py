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

Generate Verilog-AMS (.va) files that accurately replicate a circuit's transfer characteristic.

Verilog-AMS rules:
- First line MUST be: `include "disciplines.vams"
- When using `M_PI or `M_TWO_PI, also add: `include "constants.vams"
- Module ports: (output electrical out, input electrical in)
- Use: analog begin ... end
- Assign output voltage: V(out) <+ <expression>;
- Declare real variables with 'real' and constants with 'parameter real'
- Model operating regions with if/else (e.g. off, linear, saturation)
- No markdown fences — return pure .va code only

When AC frequency response data is provided:
- Generate a DYNAMIC behavioral model that captures bandwidth, not just DC gain.
- Use laplace_nd() for a first-order lowpass with input bias offset:
    parameter real vmid = (voh + vol) / 2.0;   // output midpoint
    V(out) <+ min(voh, max(vol, vmid + gain * laplace_nd(V(in) - vth, {1.0}, {1.0, tau})));
  where:
    vth  = input threshold voltage (midpoint of S-curve, from Vth metric)
    vmid = (voh + vol) / 2.0  (output midpoint)
    tau  = 1.0 / (2.0 * `M_PI * 2.0 * bw_hz)  (RC time constant)
- The bias offset V(in) - vth centres the linear amplification on the correct
  operating point. Without it, gain * V(in) saturates for all biased circuits.
- The laplace_nd(signal, num_coeffs, den_coeffs) function models H(s)=N(s)/D(s).
  For H(s) = 1/(1+s*tau): num={1.0}, den={1.0, tau}."""


# ── Prompt builders ────────────────────────────────────────────────────

def _build_prompt(netlist, x, y, info, metrics=None, ac_metrics=None):
    lines = [
        "Generate a Verilog-AMS behavioral model for the circuit below.",
        "",
        "## SPICE Netlist",
        netlist.strip(),
        "",
    ]
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
    if metrics is not None:
        lines += [
            "",
            "## Key DC Behavioral Metrics",
            f"  VOH  (output-high voltage) = {metrics['voh']:.4f} V",
            f"  VOL  (output-low  voltage) = {metrics['vol']:.4f} V",
            f"  Vth  (input threshold)     = {metrics['vth']:.4f} V",
            f"  Gain (peak |dVout/dVin|)   = {metrics['gain']:.2f} V/V",
        ]
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
        idx_ac = np.round(np.linspace(0, len(freqs) - 1,
                                      min(20, len(freqs)))).astype(int)
        for i in idx_ac:
            lines.append(
                f"{float(freqs[i]):>16.3e}  "
                f"{float(mag_db[i]):>10.2f}  "
                f"{float(phases[i]):>10.1f}"
            )
        lines += ["",
                  f"  DC gain  = {ac_metrics['dc_gain_db']:.2f} dB"
                  f"  ({ac_metrics['dc_gain_linear']:.1f} V/V)"]
        if ac_metrics['bw_3db_hz']:
            import math as _math
            tau = 1.0 / (2.0 * _math.pi * ac_metrics['bw_3db_hz'])
            lines += [
                f"  -3dB BW  = {ac_metrics['bw_3db_hz'] / 1e6:.3f} MHz",
                f"  tau      = {tau * 1e9:.3f} ns  "
                f"(use as the denominator coefficient in laplace_nd)",
                "",
                "Use laplace_nd with input bias offset (vth from metrics above):",
                "  parameter real vmid = (voh + vol) / 2.0;",
                "  V(out) <+ min(voh, max(vol, vmid + gain * laplace_nd(V(in) - vth, {1.0}, {1.0, tau})));",
                "  // V(in) - vth centres amplification on the operating point",
            ]
    lines += [
        "",
        f"Signal input: source={info['signal_source']}, "
        f"output node='{info['output_node']}', VDD={info['vdd']} V",
        "",
        "Generate the Verilog-AMS module:",
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
    return text


# ── Ollama backend ─────────────────────────────────────────────────────

class OllamaAgent:
    DEFAULT_MODEL = "qwen2.5-coder:7b"
    BASE_URL      = "http://localhost:11434"

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

def generate(agent, netlist, x, y, info, metrics=None, ac_metrics=None):
    """Initial Verilog-AMS generation."""
    name = f"{type(agent).__name__}/{getattr(agent, 'model', '?')}"
    print(f"      [{name}] generating...", end="", flush=True)
    code = clean_code(agent.chat(
        SYSTEM_PROMPT,
        _build_prompt(netlist, x, y, info, metrics=metrics, ac_metrics=ac_metrics),
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
