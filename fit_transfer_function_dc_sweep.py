#!/usr/bin/env python3
"""
fit_transfer_function.py

Purpose:
- Consume DC sweep data (control axis -> output)
- Classify intent numerically
- Extract region-aware transfer functions
- Apply smooth boundary blending (solver-safe)
- Decide: analytic vs LUT/table

Device-agnostic.
"""

import numpy as np

# ============================================================
# Numerical helpers
# ============================================================

def numerical_derivative(x, y):
    return np.gradient(y, x)


def detect_threshold(x, y, eps=1e-9):
    idx = np.where(np.abs(y) > eps)[0]
    return x[idx[0]] if len(idx) else None


# ============================================================
# Intent classification
# ============================================================

def classify_intent(x, y):
    dy_dx = numerical_derivative(x, y)
    mean_slope = np.mean(np.abs(dy_dx)) + 1e-12

    if np.std(dy_dx) / mean_slope < 0.05:
        return "linear"

    if np.all(dy_dx >= -1e-12):
        return "saturating"

    return "switching"


# ============================================================
# Region-aware fitting
# ============================================================

def fit_linear(x, y):
    a, b = np.polyfit(x, y, 1)
    return {
        "model": "linear",
        "regions": [{
            "range": "all",
            "expr": "a*x + b",
            "params": {"a": a, "b": b}
        }]
    }


def fit_saturating_with_smoothing(x, y):
    Vth = detect_threshold(x, y)
    if Vth is None:
        raise ValueError("Threshold not detected")

    mask = x >= Vth
    x_eff = x[mask] - Vth
    y_eff = y[mask]

    k, _, _, _ = np.linalg.lstsq((x_eff**2)[:, None], y_eff, rcond=None)
    k = k[0]

    # smoothing width from sweep resolution
    dx = np.mean(np.diff(x))
    delta = 2 * dx

    return {
        "model": "saturating",
        "regions": [
            {
                "name": "off",
                "expr": "0",
                "range": f"x << {Vth:.4f}"
            },
            {
                "name": "on",
                "expr": "k*(x - Vth)**2",
                "range": f"x >> {Vth:.4f}"
            }
        ],
        "smoothing": {
            "type": "tanh_blend",
            "center": Vth,
            "width": delta
        },
        "params": {
            "k": k,
            "Vth": Vth,
            "delta": delta
        }
    }


# ============================================================
# Validation
# ============================================================

def eval_saturating(x, params):
    Vth = params["Vth"]
    k = params["k"]
    return np.where(x >= Vth, k * (x - Vth)**2, 0.0)


def compute_fit_error(y_true, y_pred):
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
    nrmse = rmse / (np.ptp(y_true) + 1e-12)
    return nrmse


# ============================================================
# Main API
# ============================================================

def fit_transfer_function(x, y, error_limit=0.05):
    intent = classify_intent(x, y)

    if intent == "switching":
        return {
            "intent": "switching",
            "model_type": "LUT",
            "reason": "non-monotonic or abrupt transition"
        }

    if intent == "linear":
        model = fit_linear(x, y)
        y_hat = model["regions"][0]["params"]["a"] * x + \
                model["regions"][0]["params"]["b"]
    else:
        model = fit_saturating_with_smoothing(x, y)
        y_hat = eval_saturating(x, model["params"])

    nrmse = compute_fit_error(y, y_hat)

    if nrmse > error_limit:
        return {
            "intent": intent,
            "model_type": "LUT",
            "reason": "analytic fit error too large",
            "nrmse": nrmse
        }

    return {
        "intent": intent,
        "model_type": "analytic",
        "nrmse": nrmse,
        "model": model
    }


# ============================================================
# Example
# ============================================================

if __name__ == "__main__":
    x = np.linspace(0, 1.5, 31)
    y = np.where(x > 0.4, 4.2e-5 * (x - 0.4)**2, 0)

    result = fit_transfer_function(x, y)

    print("Intent:", result["intent"])
    print("Model type:", result["model_type"])
    print("NRMSE:", result["nrmse"])
    print("Model description:")
    print(result["model"])

