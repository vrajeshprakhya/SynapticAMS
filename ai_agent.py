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

Generate Verilog-AMS (.va) files that accurately replicate a circuit's DC transfer characteristic.

Verilog-AMS rules:
- First line: `include "disciplines.vams"
- Module ports: (output electrical <out>, input electrical <in>)
- Use: analog begin ... end
- Assign output voltage: V(<out>) <+ <expression>;
- Declare real variables and parameters
- Model operating regions with if/else (e.g. off, linear, saturation)
- No markdown fences — return pure .va code only"""


# ── Prompt builders ────────────────────────────────────────────────────

def _build_prompt(netlist, x, y, info):
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

    # Extract `parameter real name = value;`
    params = {}
    for m in re.finditer(r"parameter\s+real\s+(\w+)\s*=\s*([^;,\n]+)", va_code):
        try:
            params[m.group(1)] = float(m.group(2).strip())
        except ValueError:
            pass

    def _to_py(expr):
        """Translate a Verilog-AMS expression to a Python-evaluable string."""
        expr = re.sub(r"\bV\s*\([^)]+\)", "x_val", expr)
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
    """Strip markdown fences that LLMs sometimes wrap responses in."""
    text = re.sub(r"```(?:verilog(?:-ams)?|vams)?\n?", "", text, flags=re.I)
    return text.strip()


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

def generate(agent, netlist, x, y, info):
    """Initial Verilog-AMS generation."""
    name = f"{type(agent).__name__}/{getattr(agent, 'model', '?')}"
    print(f"      [{name}] generating...", end="", flush=True)
    code = clean_code(agent.chat(SYSTEM_PROMPT, _build_prompt(netlist, x, y, info)))
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
