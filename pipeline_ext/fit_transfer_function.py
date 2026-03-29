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
# DC Primitive Detection
# ============================================================

def detect_dc_primitives(x, y):
    """
    Detect which DC primitive(s) best describe the transfer function

    Primitives:
    - constant: y ≈ c
    - linear: y = ax + b
    - exp: y = a*exp(bx)
    - poly: y = polynomial(x)
    - sigmoid: y = tanh-like or logistic
    - piecewise: different regions
    - threshold: step function
    - switching: sign changes

    Returns:
        list of (primitive_name, confidence) tuples
    """
    eps = 1e-12
    dy = numerical_derivative(x, y)

    # Normalize for comparisons
    y_range = np.max(y) - np.min(y)
    if y_range < eps:
        return [('constant', 1.0)]

    y_norm = (y - np.min(y)) / y_range

    detected = []

    # Test 1: Constant (y doesn't change)
    if np.std(y) < 0.01 * (np.abs(np.mean(y)) + eps):
        detected.append(('constant', 1.0))
        return detected  # If constant, nothing else applies

    # Test 2: Linear (derivative is constant)
    dy_variance = np.std(dy) / (np.mean(np.abs(dy)) + eps)
    if dy_variance < 0.05:
        # Compute R² for linear fit
        a, b = np.polyfit(x, y, 1)
        y_linear = a * x + b
        ss_res = np.sum((y - y_linear)**2)
        ss_tot = np.sum((y - np.mean(y))**2)
        r2 = 1 - ss_res / (ss_tot + eps)
        if r2 > 0.98:
            detected.append(('linear', r2))

    # Test 3: Exponential (log(y) vs x is linear)
    y_positive = y - np.min(y) + eps
    if np.all(y_positive > 0):
        try:
            log_y = np.log(y_positive)
            a, b = np.polyfit(x, log_y, 1)
            log_y_fit = a * x + b
            ss_res = np.sum((log_y - log_y_fit)**2)
            ss_tot = np.sum((log_y - np.mean(log_y))**2)
            r2_exp = 1 - ss_res / (ss_tot + eps)
            if r2_exp > 0.95:
                detected.append(('exp', r2_exp))
        except:
            pass

    # Test 4: Polynomial (try degree 2, 3)
    for degree in [2, 3]:
        coeffs = np.polyfit(x, y, degree)
        y_poly = np.polyval(coeffs, x)
        ss_res = np.sum((y - y_poly)**2)
        ss_tot = np.sum((y - np.mean(y))**2)
        r2_poly = 1 - ss_res / (ss_tot + eps)
        if r2_poly > 0.95:
            detected.append((f'poly{degree}', r2_poly))

    # Test 5: Sigmoid (S-shaped curve)
    # Check if derivative has single peak
    if len(dy) > 5:
        d2y = np.gradient(dy)
        # Find inflection point (where d2y crosses zero)
        zero_crossings = np.where(np.diff(np.sign(d2y)))[0]
        if len(zero_crossings) == 1:
            # Single inflection point → sigmoid-like
            # Try fitting to tanh
            try:
                from scipy.optimize import curve_fit
                def sigmoid(x, a, b, c, d):
                    return a + b / (1 + np.exp(-(x - c) / d))

                popt, _ = curve_fit(sigmoid, x, y, maxfev=1000)
                y_sigmoid = sigmoid(x, *popt)
                ss_res = np.sum((y - y_sigmoid)**2)
                ss_tot = np.sum((y - np.mean(y))**2)
                r2_sigmoid = 1 - ss_res / (ss_tot + eps)
                if r2_sigmoid > 0.95:
                    detected.append(('sigmoid', r2_sigmoid))
            except:
                pass

    # Test 6: Piecewise (multiple regions with different slopes)
    # Detect abrupt slope changes
    if len(dy) > 10:
        d2y = np.gradient(dy)
        # Count significant slope changes
        slope_changes = np.where(np.abs(d2y) > 2 * np.std(d2y))[0]
        if len(slope_changes) >= 2:
            detected.append(('piecewise', 0.8))

    # Test 7: Threshold (step function)
    # Check if output stays near min, then jumps to max
    y_low = np.min(y)
    y_high = np.max(y)
    y_mid = (y_low + y_high) / 2

    near_low = np.sum(y < y_mid) / len(y)
    near_high = np.sum(y > y_mid) / len(y)

    if (near_low > 0.3 and near_high > 0.3) and (near_low + near_high > 0.9):
        # Most points are either near min or near max
        detected.append(('threshold', 0.9))

    # Test 8: Switching (derivative changes sign)
    dy_sign_changes = np.sum(np.diff(np.sign(dy)) != 0)
    if dy_sign_changes > 0:
        detected.append(('switching', min(1.0, dy_sign_changes / 3)))

    # If no primitives detected, default to generic polynomial
    if not detected:
        detected.append(('poly3', 0.5))

    # Sort by confidence
    detected.sort(key=lambda x: x[1], reverse=True)

    return detected


def classify_intent(x, y):
    """
    Classify transfer function intent (backward compatibility)
    Returns single best primitive
    """
    primitives = detect_dc_primitives(x, y)

    if not primitives:
        return "switching"

    best_primitive, confidence = primitives[0]

    # Map to legacy names for existing code
    mapping = {
        'constant': 'linear',
        'linear': 'linear',
        'exp': 'saturating',
        'poly2': 'saturating',
        'poly3': 'saturating',
        'sigmoid': 'saturating',
        'piecewise': 'switching',
        'threshold': 'switching',
        'switching': 'switching'
    }

    return mapping.get(best_primitive, 'switching')


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
    """
    Fit 1D transfer function using detected DC primitives

    Now uses comprehensive primitive detection instead of 3 hard-coded categories
    """
    # Detect primitives (sorted by confidence)
    primitives = detect_dc_primitives(x, y)

    # Try fitting models based on detected primitives
    for primitive, confidence in primitives:

        if primitive == 'constant':
            # Constant output
            model = {
                "model": "constant",
                "regions": [{
                    "range": "all",
                    "expr": "c",
                    "params": {"c": np.mean(y)}
                }]
            }
            y_hat = np.full_like(y, np.mean(y))

        elif primitive == 'linear':
            model = fit_linear(x, y)
            y_hat = model["regions"][0]["params"]["a"] * x + \
                    model["regions"][0]["params"]["b"]

        elif primitive == 'exp':
            # Exponential fit
            try:
                y_positive = y - np.min(y) + 1e-12
                log_y = np.log(y_positive)
                a, b = np.polyfit(x, log_y, 1)
                c = np.min(y)
                model = {
                    "model": "exponential",
                    "regions": [{
                        "range": "all",
                        "expr": "c + exp(a*x + b)",
                        "params": {"a": a, "b": b, "c": c}
                    }]
                }
                y_hat = c + np.exp(a * x + b)
            except:
                continue

        elif primitive.startswith('poly'):
            # Polynomial fit
            degree = int(primitive[-1])
            coeffs = np.polyfit(x, y, degree)
            model = {
                "model": f"polynomial_{degree}",
                "regions": [{
                    "range": "all",
                    "expr": f"poly{degree}(x)",
                    "params": {f"c{i}": float(coeffs[i]) for i in range(len(coeffs))}
                }]
            }
            y_hat = np.polyval(coeffs, x)

        elif primitive == 'sigmoid':
            # Sigmoid/logistic fit
            try:
                from scipy.optimize import curve_fit
                def sigmoid(x, a, b, c, d):
                    return a + b / (1 + np.exp(-(x - c) / d))

                popt, _ = curve_fit(sigmoid, x, y, maxfev=1000)
                model = {
                    "model": "sigmoid",
                    "regions": [{
                        "range": "all",
                        "expr": "a + b/(1 + exp(-(x-c)/d))",
                        "params": {"a": popt[0], "b": popt[1], "c": popt[2], "d": popt[3]}
                    }]
                }
                y_hat = sigmoid(x, *popt)
            except:
                continue

        elif primitive in ['piecewise', 'threshold', 'switching']:
            # These need LUT
            return {
                "intent": primitive,
                "model_type": "LUT",
                "reason": f"{primitive} behavior detected",
                "primitives": primitives
            }

        else:
            continue

        # Check fit quality
        nrmse = compute_fit_error(y, y_hat)

        if nrmse < error_limit:
            # Good fit!
            return {
                "intent": primitive,
                "model_type": "analytic",
                "nrmse": nrmse,
                "model": model,
                "primitives": primitives,
                "confidence": confidence
            }

    # No analytic fit worked - fall back to LUT
    best_primitive = primitives[0][0] if primitives else "unknown"
    return {
        "intent": best_primitive,
        "model_type": "LUT",
        "reason": "no analytic fit within error limit",
        "nrmse": float('inf'),
        "primitives": primitives
    }


# ============================================================
# 2D Transfer Function Fitting
# ============================================================

def classify_surface_behavior(x1, x2, z):
    """
    Analyze a 2D surface to guide model selection (like classify_intent for 1D)

    Returns:
        dict: {
            'differential_mode': bool,  # Responds to x1-x2
            'has_cross_coupling': bool,  # x1 and x2 interact
            'linearity': float,          # 0=linear, 1=highly nonlinear
            'symmetry': float            # How symmetric in x1 vs x2
        }
    """
    # Create meshgrid
    X1, X2 = np.meshgrid(x1, x2, indexing='ij')

    # Test 1: Check if surface responds to difference (x1-x2)
    # Compare correlation of z with (x1-x2) vs correlation with (x1+x2)
    diff_mode = X1 - X2
    common_mode = X1 + X2

    corr_diff = np.corrcoef(diff_mode.ravel(), z.ravel())[0, 1]
    corr_common = np.corrcoef(common_mode.ravel(), z.ravel())[0, 1]

    is_differential = abs(corr_diff) > 0.7 and abs(corr_diff) > abs(corr_common)

    # Test 2: Check for cross-coupling (interaction term x1*x2)
    # Fit with and without interaction term, compare improvement
    from sklearn.linear_model import LinearRegression

    X_no_interaction = np.column_stack([X1.ravel(), X2.ravel()])
    X_with_interaction = np.column_stack([X1.ravel(), X2.ravel(), (X1*X2).ravel()])

    model_no_int = LinearRegression().fit(X_no_interaction, z.ravel())
    model_with_int = LinearRegression().fit(X_with_interaction, z.ravel())

    r2_no_int = model_no_int.score(X_no_interaction, z.ravel())
    r2_with_int = model_with_int.score(X_with_interaction, z.ravel())

    has_interaction = (r2_with_int - r2_no_int) > 0.01  # >1% improvement

    # Test 3: Measure nonlinearity (variance of second derivatives)
    dz_dx1 = np.gradient(z, axis=0)
    dz_dx2 = np.gradient(z, axis=1)
    d2z_dx1 = np.gradient(dz_dx1, axis=0)
    d2z_dx2 = np.gradient(dz_dx2, axis=1)

    nonlinearity = (np.std(d2z_dx1) + np.std(d2z_dx2)) / (np.std(z) + 1e-12)

    # Test 4: Measure symmetry (how similar is response to x1 vs x2)
    # Compare marginal effects
    effect_x1 = np.std(np.mean(z, axis=1))  # Variation when averaging over x2
    effect_x2 = np.std(np.mean(z, axis=0))  # Variation when averaging over x1

    symmetry = min(effect_x1, effect_x2) / (max(effect_x1, effect_x2) + 1e-12)

    return {
        'differential_mode': is_differential,
        'has_cross_coupling': has_interaction,
        'linearity': 1.0 - min(nonlinearity, 1.0),  # 1=linear, 0=highly nonlinear
        'symmetry': symmetry  # 1=symmetric, 0=asymmetric
    }


def fit_transfer_function_2d(x1, x2, z, error_limit=0.10):
    """
    Fit a 2D transfer function z = f(x1, x2) using DATA-DRIVEN model selection

    Like the 1D version, we ANALYZE the surface first, then choose models

    Args:
        x1: 1D array of first input values
        x2: 1D array of second input values
        z: 2D array of output values (shape: len(x1) × len(x2))
        error_limit: Maximum normalized RMS error for analytic fit

    Returns:
        dict: {
            'intent': str,
            'model_type': 'analytic' or 'LUT_2D',
            'model': dict (for analytic) or None (for LUT),
            'nrmse': float
        }
    """
    # Create meshgrid for fitting
    X1, X2 = np.meshgrid(x1, x2, indexing='ij')
    X1_flat = X1.ravel()
    X2_flat = X2.ravel()
    Z_flat = z.ravel()

    # STEP 1: ANALYZE the surface (like classify_intent in 1D)
    behavior = classify_surface_behavior(x1, x2, z)

    # STEP 2: SELECT models based on analysis (data-driven!)
    models_to_try = []

    if behavior['differential_mode']:
        # Surface responds to difference → try differential models first
        models_to_try.append(('differential', _fit_differential_2d))
        models_to_try.append(('differential_squared', _fit_differential_squared_2d))

    if behavior['has_cross_coupling']:
        # Inputs interact → include interaction term
        models_to_try.append(('bilinear', _fit_bilinear_2d))
        models_to_try.append(('quadratic', _fit_quadratic_2d))

    if behavior['linearity'] > 0.8:
        # Nearly linear → try simple models
        models_to_try.insert(0, ('bilinear', _fit_bilinear_2d))
    else:
        # Highly nonlinear → try higher-order models
        models_to_try.append(('quadratic', _fit_quadratic_2d))

    # Always have a fallback
    if not models_to_try:
        models_to_try = [
            ('bilinear', _fit_bilinear_2d),
            ('quadratic', _fit_quadratic_2d)
        ]

    # STEP 3: TRY selected models (fewer attempts, smarter selection)
    best_model = None
    best_nrmse = float('inf')
    best_name = None

    for name, fit_func in models_to_try:
        try:
            model = fit_func(X1_flat, X2_flat, Z_flat)
            z_hat = _eval_2d_model(X1, X2, model)
            nrmse = compute_fit_error(z, z_hat)

            if nrmse < best_nrmse:
                best_nrmse = nrmse
                best_model = model
                best_name = name

            # Early exit if we found a good fit
            if nrmse < error_limit / 2:
                break

        except Exception:
            continue

    # STEP 4: VALIDATE and decide (like 1D version)
    if best_model is not None and best_nrmse < error_limit:
        return {
            'intent': best_name,
            'model_type': 'analytic',
            'model': best_model,
            'nrmse': best_nrmse,
            'analysis': behavior  # Include analysis for debugging
        }
    else:
        # Fall back to 2D LUT
        return {
            'intent': 'coupled_nonlinear',
            'model_type': 'LUT_2D',
            'reason': 'analytic fit error too large',
            'nrmse': best_nrmse if best_model else float('inf'),
            'analysis': behavior
        }


def _fit_differential_2d(X1_flat, X2_flat, Z_flat):
    """
    Fit differential model: z = a + b*(x1-x2) + c*(x1-x2)^2
    Good for differential pairs
    """
    Vdiff = X1_flat - X2_flat

    # Build design matrix: [1, Vdiff, Vdiff^2]
    A = np.column_stack([
        np.ones_like(Vdiff),
        Vdiff,
        Vdiff**2
    ])

    # Least squares fit
    coeffs, _, _, _ = np.linalg.lstsq(A, Z_flat, rcond=None)

    return {
        'type': 'differential',
        'expr': 'a + b*(x1-x2) + c*(x1-x2)^2',
        'params': {
            'a': float(coeffs[0]),
            'b': float(coeffs[1]),
            'c': float(coeffs[2])
        }
    }


def _fit_differential_squared_2d(X1_flat, X2_flat, Z_flat):
    """
    Fit differential squared model: z = a + b*(x1-x2)^2 + c*(x1-x2)^3
    Good for highly nonlinear differential circuits
    """
    Vdiff = X1_flat - X2_flat

    # Build design matrix: [1, Vdiff^2, Vdiff^3]
    A = np.column_stack([
        np.ones_like(Vdiff),
        Vdiff**2,
        Vdiff**3
    ])

    # Least squares fit
    coeffs, _, _, _ = np.linalg.lstsq(A, Z_flat, rcond=None)

    return {
        'type': 'differential_squared',
        'expr': 'a + b*(x1-x2)^2 + c*(x1-x2)^3',
        'params': {
            'a': float(coeffs[0]),
            'b': float(coeffs[1]),
            'c': float(coeffs[2])
        }
    }


def _fit_bilinear_2d(X1_flat, X2_flat, Z_flat):
    """
    Fit bilinear model: z = a + b*x1 + c*x2 + d*x1*x2
    """
    # Build design matrix: [1, x1, x2, x1*x2]
    A = np.column_stack([
        np.ones_like(X1_flat),
        X1_flat,
        X2_flat,
        X1_flat * X2_flat
    ])

    # Least squares fit
    coeffs, _, _, _ = np.linalg.lstsq(A, Z_flat, rcond=None)

    return {
        'type': 'bilinear',
        'expr': 'a + b*x1 + c*x2 + d*x1*x2',
        'params': {
            'a': float(coeffs[0]),
            'b': float(coeffs[1]),
            'c': float(coeffs[2]),
            'd': float(coeffs[3])
        }
    }


def _fit_quadratic_2d(X1_flat, X2_flat, Z_flat):
    """
    Fit quadratic model: z = a + b*x1 + c*x2 + d*x1^2 + e*x2^2 + f*x1*x2
    """
    # Build design matrix
    A = np.column_stack([
        np.ones_like(X1_flat),
        X1_flat,
        X2_flat,
        X1_flat**2,
        X2_flat**2,
        X1_flat * X2_flat
    ])

    # Least squares fit
    coeffs, _, _, _ = np.linalg.lstsq(A, Z_flat, rcond=None)

    return {
        'type': 'quadratic',
        'expr': 'a + b*x1 + c*x2 + d*x1^2 + e*x2^2 + f*x1*x2',
        'params': {
            'a': float(coeffs[0]),
            'b': float(coeffs[1]),
            'c': float(coeffs[2]),
            'd': float(coeffs[3]),
            'e': float(coeffs[4]),
            'f': float(coeffs[5])
        }
    }


def _eval_2d_model(X1, X2, model):
    """
    Evaluate a 2D model at given input points

    Args:
        X1, X2: Meshgrid arrays
        model: Model dict from _fit_*_2d functions

    Returns:
        Z: Evaluated surface (same shape as X1, X2)
    """
    params = model['params']
    model_type = model['type']

    if model_type == 'differential':
        Vdiff = X1 - X2
        return params['a'] + params['b']*Vdiff + params['c']*Vdiff**2

    elif model_type == 'differential_squared':
        Vdiff = X1 - X2
        return params['a'] + params['b']*Vdiff**2 + params['c']*Vdiff**3

    elif model_type == 'bilinear':
        return (params['a'] +
                params['b']*X1 +
                params['c']*X2 +
                params['d']*X1*X2)

    elif model_type == 'quadratic':
        return (params['a'] +
                params['b']*X1 +
                params['c']*X2 +
                params['d']*X1**2 +
                params['e']*X2**2 +
                params['f']*X1*X2)

    else:
        raise ValueError(f"Unknown model type: {model_type}")


# ============================================================
# Transient Waveform Analysis
# ============================================================

def analyze_oscillator_waveform(time, voltage):
    """
    Analyze a transient waveform to extract oscillator characteristics.

    Args:
        time: 1D array of time points (seconds)
        voltage: 1D array of voltage samples

    Returns:
        dict: {
            'frequency': float (Hz),
            'amplitude': float (V),
            'offset': float (V),
            'period': float (s),
            'duty_cycle': float (0-1),
            'is_oscillating': bool,
            'quality': float (0-1, measure of waveform quality)
        }
    """
    if len(time) < 10 or len(voltage) < 10:
        return {
            'is_oscillating': False,
            'frequency': 0.0,
            'amplitude': 0.0,
            'offset': np.mean(voltage),
            'period': 0.0,
            'duty_cycle': 0.5,
            'quality': 0.0
        }

    # Remove DC offset
    offset = np.mean(voltage)
    v_ac = voltage - offset

    # Check if signal is actually oscillating (non-constant)
    if np.std(v_ac) < 1e-6:
        return {
            'is_oscillating': False,
            'frequency': 0.0,
            'amplitude': 0.0,
            'offset': offset,
            'period': 0.0,
            'duty_cycle': 0.5,
            'quality': 0.0
        }

    # Detect zero crossings to find period
    zero_crossings = np.where(np.diff(np.sign(v_ac)))[0]

    if len(zero_crossings) < 2:
        # Not enough crossings - not oscillating
        return {
            'is_oscillating': False,
            'frequency': 0.0,
            'amplitude': np.ptp(voltage) / 2,
            'offset': offset,
            'period': 0.0,
            'duty_cycle': 0.5,
            'quality': 0.0
        }

    # Calculate periods from consecutive zero crossings (half periods)
    half_periods = np.diff(time[zero_crossings])

    # Full period is 2x half-period
    # Handle odd number of half-periods by truncating to even length
    n_pairs = len(half_periods) // 2
    if n_pairs > 0:
        periods = half_periods[:n_pairs*2:2] + half_periods[1:n_pairs*2:2]
    else:
        periods = half_periods * 2

    if len(periods) == 0:
        periods = half_periods * 2

    # Use median period (robust to outliers)
    period = np.median(periods)
    frequency = 1.0 / period if period > 0 else 0.0

    # Measure amplitude (peak-to-peak / 2)
    amplitude = np.ptp(v_ac) / 2

    # Estimate duty cycle from positive vs negative time
    positive_time = np.sum(v_ac > 0) * (time[1] - time[0])
    total_time = time[-1] - time[0]
    duty_cycle = positive_time / total_time if total_time > 0 else 0.5

    # Quality metric: coefficient of variation of periods
    # Lower variation = better quality oscillation
    period_std = np.std(periods)
    period_mean = np.mean(periods)
    cv = period_std / period_mean if period_mean > 0 else 1.0
    quality = max(0.0, 1.0 - cv)  # 1.0 = perfect, 0.0 = chaotic

    return {
        'is_oscillating': True,
        'frequency': frequency,
        'amplitude': amplitude,
        'offset': offset,
        'period': period,
        'duty_cycle': duty_cycle,
        'quality': quality,
        'num_cycles': len(periods)
    }


def fit_oscillator_model(time, voltage):
    """
    Fit an oscillator model from transient waveform data.

    Args:
        time: 1D array of time points
        voltage: 1D array of voltage samples

    Returns:
        dict: Model parameters suitable for Verilog-AMS generation
    """
    # Analyze waveform
    analysis = analyze_oscillator_waveform(time, voltage)

    if not analysis['is_oscillating']:
        # Not an oscillator - return constant model
        return {
            'model_type': 'constant',
            'intent': 'dc',
            'params': {
                'value': analysis['offset']
            }
        }

    # Determine waveform shape
    waveform_type = _classify_waveform_shape(time, voltage, analysis)

    return {
        'model_type': 'oscillator',
        'intent': 'dynamic',
        'waveform': waveform_type,
        'params': {
            'frequency': analysis['frequency'],
            'amplitude': analysis['amplitude'],
            'offset': analysis['offset'],
            'duty_cycle': analysis['duty_cycle'],
            'period': analysis['period']
        },
        'quality': analysis['quality'],
        'num_cycles': analysis.get('num_cycles', 0)
    }


def _classify_waveform_shape(time, voltage, analysis):
    """
    Classify the shape of an oscillating waveform.

    Returns:
        str: 'sine', 'square', 'triangle', or 'complex'
    """
    # Normalize waveform
    v_norm = (voltage - analysis['offset']) / (analysis['amplitude'] + 1e-12)

    # Test 1: Square wave (sharp transitions, mostly at +1 or -1)
    near_extremes = np.sum(np.abs(v_norm) > 0.8) / len(v_norm)
    if near_extremes > 0.7:
        return 'square'

    # Test 2: Sine wave (smooth, single frequency FFT)
    try:
        from scipy import fft
        spectrum = np.abs(fft.fft(v_norm))
        fundamental_idx = np.argmax(spectrum[1:len(spectrum)//2]) + 1
        fundamental_power = spectrum[fundamental_idx]
        total_power = np.sum(spectrum[1:len(spectrum)//2])

        # If >90% power in fundamental, it's sinusoidal
        if fundamental_power / total_power > 0.9:
            return 'sine'
    except:
        pass

    # Test 3: Triangle (linear ramp, derivative mostly constant)
    dv = np.diff(v_norm)
    dv_variance = np.std(np.abs(dv))
    dv_mean = np.mean(np.abs(dv))

    if dv_variance / (dv_mean + 1e-12) < 0.3:
        return 'triangle'

    # Default: complex waveform
    return 'complex'


# ============================================================
# Dynamic Transfer Function (DC + Transient Combined)
# ============================================================

def analyze_step_response(time, voltage, input_step_size=1.0):
    """
    Analyze a transient step response to extract dynamic characteristics.

    Args:
        time: 1D array of time points (seconds)
        voltage: 1D array of output voltage response
        input_step_size: Magnitude of input step (V)

    Returns:
        dict: {
            'dc_gain': float (from final value),
            'rise_time': float (10% to 90% in seconds),
            'settling_time': float (to within 2% of final value),
            'bandwidth': float (estimated -3dB bandwidth in Hz),
            'time_constant': float (tau in seconds),
            'overshoot': float (percentage overshoot),
            'is_valid': bool (True if step response is usable)
        }
    """
    if len(time) < 10 or len(voltage) < 10:
        return {
            'is_valid': False,
            'dc_gain': 0.0,
            'rise_time': 0.0,
            'settling_time': 0.0,
            'bandwidth': 0.0,
            'time_constant': 0.0,
            'overshoot': 0.0
        }

    # Extract initial and final values
    initial_value = voltage[0]
    final_value = voltage[-1]

    # Check if there's actually a step response
    delta_v = abs(final_value - initial_value)
    if delta_v < 1e-9:
        # No response - might be open circuit or no input
        return {
            'is_valid': False,
            'dc_gain': 0.0,
            'rise_time': 0.0,
            'settling_time': 0.0,
            'bandwidth': 0.0,
            'time_constant': 0.0,
            'overshoot': 0.0
        }

    # Calculate DC gain (output change / input change)
    dc_gain = delta_v / abs(input_step_size) if input_step_size != 0 else 0.0

    # Normalize response to 0-1 range
    v_norm = (voltage - initial_value) / delta_v

    # Find 10% and 90% points for rise time
    idx_10 = np.argmax(v_norm >= 0.1)
    idx_90 = np.argmax(v_norm >= 0.9)

    if idx_10 >= idx_90:
        # Invalid rise time (might be falling edge or noisy)
        rise_time = time[-1] - time[0]  # Use total time as fallback
    else:
        rise_time = time[idx_90] - time[idx_10]

    # Estimate bandwidth from rise time (for first-order system: BW ≈ 0.35/t_rise)
    bandwidth = 0.35 / rise_time if rise_time > 0 else 0.0

    # Find settling time (to within 2% of final value)
    tolerance = 0.02
    settled = np.abs(v_norm - 1.0) < tolerance

    if np.any(settled):
        # Find first point where it settles and stays settled
        settled_idx = np.argmax(settled)
        settling_time = time[settled_idx]
    else:
        # Never settled within tolerance
        settling_time = time[-1]

    # Calculate time constant (tau) from exponential fit
    # For first-order: V(t) = Vf * (1 - exp(-t/tau))
    # At t=tau, V = 0.632 * Vf
    try:
        idx_tau = np.argmax(v_norm >= 0.632)
        time_constant = time[idx_tau] - time[0] if idx_tau > 0 else rise_time / 2.2
    except:
        time_constant = rise_time / 2.2  # Approximate for first-order system

    # Calculate overshoot
    peak_value = np.max(v_norm)
    overshoot = max(0.0, (peak_value - 1.0) * 100.0)  # Percentage

    return {
        'is_valid': True,
        'dc_gain': dc_gain,
        'rise_time': rise_time,
        'settling_time': settling_time,
        'bandwidth': bandwidth,
        'time_constant': time_constant,
        'overshoot': overshoot,
        'initial_value': initial_value,
        'final_value': final_value
    }


def fit_dynamic_transfer_function(dc_x, dc_y, transient_time=None, transient_voltage=None,
                                   input_step_size=1.0):
    """
    Combine DC sweep and transient step response into a unified transfer function.

    This function creates models for DRIVEN circuits (amplifiers, filters) that combines:
    - DC gain from DC sweep
    - Bandwidth/dynamics from transient step response

    Args:
        dc_x: DC sweep input voltage array (or None if no DC data)
        dc_y: DC sweep output voltage array (or None if no DC data)
        transient_time: Transient simulation time array (or None if no transient)
        transient_voltage: Transient output voltage array (or None if no transient)
        input_step_size: Size of input step applied in transient (V)

    Returns:
        dict: {
            'model_type': 'dynamic',
            'intent': 'amplifier'/'filter'/'buffer',
            'dc_model': dict (from DC sweep fitting),
            'transient_model': dict (from step response),
            'combined_params': dict (unified model parameters)
        }
    """
    # Start with base model
    model = {
        'model_type': 'dynamic',
        'intent': 'amplifier',  # Default, will refine based on data
        'dc_model': None,
        'transient_model': None,
        'combined_params': {}
    }

    # STEP 1: Extract DC characteristics
    dc_gain_source = None  # Track where DC gain came from

    if dc_x is not None and dc_y is not None and len(dc_x) > 0 and len(dc_y) > 0:
        # Fit DC transfer function
        dc_result = fit_transfer_function(dc_x, dc_y)
        model['dc_model'] = dc_result

        # Extract DC gain
        if dc_result['model_type'] == 'analytic':
            # For linear: gain is slope
            if dc_result['intent'] == 'linear':
                dc_gain = dc_result['model']['regions'][0]['params']['a']
            else:
                # For nonlinear, estimate gain from endpoints
                dc_gain = (dc_y[-1] - dc_y[0]) / (dc_x[-1] - dc_x[0]) if len(dc_x) > 1 else 1.0
        else:
            # LUT - estimate from data
            dc_gain = (dc_y[-1] - dc_y[0]) / (dc_x[-1] - dc_x[0]) if len(dc_x) > 1 else 1.0

        model['combined_params']['dc_gain'] = dc_gain
        dc_gain_source = 'dc_sweep'
    else:
        model['combined_params']['dc_gain'] = None
        dc_gain_source = None

    # STEP 2: Extract transient/dynamic characteristics
    if transient_time is not None and transient_voltage is not None and \
       len(transient_time) > 0 and len(transient_voltage) > 0:

        # Analyze step response
        step_analysis = analyze_step_response(transient_time, transient_voltage, input_step_size)
        model['transient_model'] = step_analysis

        if step_analysis['is_valid']:
            # Extract dynamic parameters
            model['combined_params']['bandwidth'] = step_analysis['bandwidth']
            model['combined_params']['time_constant'] = step_analysis['time_constant']
            model['combined_params']['rise_time'] = step_analysis['rise_time']
            model['combined_params']['overshoot'] = step_analysis['overshoot']

            # If DC gain wasn't available from DC sweep, use transient
            # This is the KEY FEATURE for handling ring oscillators and circuits that can't converge to DC
            if model['combined_params']['dc_gain'] is None:
                model['combined_params']['dc_gain'] = step_analysis['dc_gain']
                dc_gain_source = 'transient'  # Extracted from transient step response

            # Classify circuit type based on characteristics
            if step_analysis['overshoot'] > 10:
                model['intent'] = 'filter'  # Significant overshoot → filtering behavior
            elif abs(step_analysis['dc_gain'] - 1.0) < 0.1:
                model['intent'] = 'buffer'  # Unity gain → buffer
            else:
                model['intent'] = 'amplifier'  # Gain ≠ 1 → amplifier
        else:
            # Invalid transient - use DC-only model
            model['combined_params']['bandwidth'] = None
            model['combined_params']['time_constant'] = None
    else:
        # No transient data
        model['combined_params']['bandwidth'] = None
        model['combined_params']['time_constant'] = None

    # STEP 3: Create unified model representation
    # This represents a first-order system: H(s) = K / (1 + s*tau)
    # where K = dc_gain, tau = time_constant

    # Add metadata about DC gain source (important for ring oscillators!)
    model['combined_params']['dc_gain_source'] = dc_gain_source

    if model['combined_params'].get('dc_gain') is not None and \
       model['combined_params'].get('time_constant') is not None:
        # Full dynamic model available
        model['combined_params']['model_class'] = 'first_order_lag'
        source_note = f" (DC from {dc_gain_source})" if dc_gain_source else ""
        model['combined_params']['transfer_function'] = (
            f"H(s) = {model['combined_params']['dc_gain']:.3e} / "
            f"(1 + s*{model['combined_params']['time_constant']:.3e}){source_note}"
        )
    elif model['combined_params'].get('dc_gain') is not None:
        # DC-only model
        model['combined_params']['model_class'] = 'dc_only'
        source_note = f" (from {dc_gain_source})" if dc_gain_source else ""
        model['combined_params']['transfer_function'] = (
            f"H(s) = {model['combined_params']['dc_gain']:.3e}{source_note}"
        )
    else:
        # No valid model
        model['combined_params']['model_class'] = 'invalid'
        model['combined_params']['transfer_function'] = None

    return model


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

