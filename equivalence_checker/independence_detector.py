#!/usr/bin/env python3
"""
independence_detector.py

Empirically tests whether multiple circuit inputs (voltage/current sources)
are independent using simulation-based coupling analysis.

Method:
- Run DC sweep of source A with source B held at different fixed values
- Compare the resulting transfer functions
- If transfer function shape changes, sources are coupled → need 2D sweep
- If transfer function only shifts, sources are independent → 1D sweeps OK
"""

import numpy as np
import re


def test_source_independence(netlist, src1, src2, output_node, runner,
                             vdd=1.8, coupling_threshold=0.05, n_test_points=3):
    """
    Empirically test if two sources are independent using simulation.

    Strategy:
    1. Sweep src1 while holding src2 at value_low
    2. Sweep src1 while holding src2 at value_high
    3. Compare transfer functions — if shape changes, they're coupled.

    Args:
        netlist:            SPICE netlist as string
        src1:               First source name (e.g. "vin")
        src2:               Second source name (e.g. "isrc")
        output_node:        Output node to observe (e.g. "vout")
        runner:             NgspiceRunner instance
        vdd:                Supply voltage (for determining sweep ranges)
        coupling_threshold: Max normalised difference for independence (0.05 = 5%)
        n_test_points:      Number of test values for src2 (default: 3)

    Returns:
        dict: {
            'coupled':          bool,
            'sources':          [src1, src2],
            'coupling_strength':float,   # 0.0 = independent, >threshold = coupled
            'recommendation':   str,     # '1D' or '2D'
            'test_details':     dict
        }
    """
    src1_device = _find_source_device_name(netlist, src1)
    src2_device = _find_source_device_name(netlist, src2)

    src1_type = _get_source_type(netlist, src1_device)
    src2_type = _get_source_type(netlist, src2_device)

    src1_range = _determine_source_range(src1_type, vdd, netlist)
    src2_range = _determine_source_range(src2_type, vdd, netlist)

    src2_test_values = np.linspace(src2_range[0], src2_range[1], n_test_points)

    curves = []
    for src2_value in src2_test_values:
        netlist_modified = _set_source_dc_value(netlist, src2_device, src2_value)

        sweep_params = {
            'sweep_var': src1,
            'start':     src1_range[0],
            'stop':      src1_range[1],
            'step':      (src1_range[1] - src1_range[0]) / 20,
            'observe':   [output_node],
        }

        try:
            results = runner.dc_sweep(netlist_modified, sweep_params)
            if output_node in results:
                curves.append({
                    'src2_value':    src2_value,
                    'src1_values':   results[src1],
                    'output_values': results[output_node],
                })
        except Exception as e:
            return {
                'coupled':          True,
                'sources':          [src1, src2],
                'coupling_strength':1.0,
                'recommendation':   '2D',
                'test_details':     {'error': str(e), 'reason': 'simulation_failure'},
            }

    if len(curves) < 2:
        return {
            'coupled':          True,
            'sources':          [src1, src2],
            'coupling_strength':1.0,
            'recommendation':   '2D',
            'test_details':     {'error': 'Insufficient simulation data'},
        }

    coupling_strength = _calculate_coupling_strength(curves)
    coupled = coupling_strength > coupling_threshold

    return {
        'coupled':          coupled,
        'sources':          [src1, src2],
        'coupling_strength':coupling_strength,
        'recommendation':   '2D' if coupled else '1D',
        'test_details': {
            'n_curves':           len(curves),
            'src2_test_values':   src2_test_values.tolist(),
            'threshold':          coupling_threshold,
            'src1_type':          src1_type,
            'src2_type':          src2_type,
        },
    }


def _find_source_device_name(netlist, node_name):
    """Return device name (e.g. 'Vinn') for a node (e.g. 'inn'), or node_name."""
    for line in netlist.split('\n'):
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue
        tokens = re.split(r'\s+', line)
        if len(tokens) < 3 or tokens[0][0].upper() not in ('V', 'I'):
            continue
        if (tokens[1].lower() == node_name.lower()
                or tokens[2].lower() == node_name.lower()):
            return tokens[0]
    return node_name


def _get_source_type(netlist, source_name):
    """Return 'V' or 'I' for the named source device."""
    for line in netlist.split('\n'):
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue
        tokens = re.split(r'\s+', line)
        if tokens and tokens[0].lower() == source_name.lower():
            return tokens[0][0].upper()
    # Fallback: find by node name
    device = _find_source_device_name(netlist, source_name)
    return device[0].upper() if device and device[0].upper() in ('V', 'I') else 'V'


def _extract_all_currents_from_netlist(netlist):
    """Return {node: current_A} for all I sources in the netlist."""
    currents = {}
    scale = {'u': 1e-6, 'µ': 1e-6, 'n': 1e-9, 'm': 1e-3,
             'k': 1e3, 'g': 1e9, 'meg': 1e6}
    for line in netlist.split('\n'):
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue
        if line[0].upper() != 'I':
            continue
        tokens = re.split(r'\s+', line)
        if len(tokens) < 4:
            continue
        pos_node = tokens[1].lower()
        neg_node = tokens[2].lower()
        m = re.search(r'DC\s+([\d.eE+-]+)\s*([uµnmkKMG]?)[Aa]?', line, re.IGNORECASE)
        if not m:
            continue
        value = float(m.group(1))
        suffix = m.group(2).lower() if m.group(2) else ''
        value *= scale.get(suffix, 1.0)
        if abs(value) < 1e-9:
            continue
        target = pos_node if neg_node in ('0', 'gnd') else neg_node
        currents[target] = abs(value)
    return currents


def _extract_max_current_from_netlist(netlist):
    """Return maximum I-source DC value in the netlist (default 100 µA)."""
    currents = _extract_all_currents_from_netlist(netlist)
    return max(currents.values()) if currents else 100e-6


def _determine_source_range(source_type, vdd, netlist=''):
    if source_type == 'V':
        return (0.0, vdd)
    max_i = _extract_max_current_from_netlist(netlist)
    return (0.0, max_i * 2.0)


def _set_source_dc_value(netlist, source_name, dc_value):
    """Return a copy of netlist with source_name's DC value replaced."""
    lines = []
    for line in netlist.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('*') or stripped.startswith('.'):
            lines.append(line)
            continue
        tokens = re.split(r'\s+', stripped)
        if not tokens or tokens[0].lower() != source_name.lower():
            lines.append(line)
            continue
        stype = tokens[0][0].upper()
        dc_str = (f"{dc_value:.6e}" if stype == 'I' and abs(dc_value) < 1e-3
                  else f"{dc_value:.6f}")
        new_tokens = tokens[:3]
        dc_idx = next((i for i, t in enumerate(tokens) if t.upper() == 'DC'), None)
        if dc_idx is not None:
            new_tokens += ['DC', dc_str] + tokens[dc_idx + 2:]
        else:
            new_tokens += ['DC', dc_str] + tokens[3:]
        lines.append(' '.join(new_tokens))
    return '\n'.join(lines)


def _calculate_coupling_strength(curves):
    """
    Return 0.0–1.0 coupling strength by comparing normalised transfer curves.
    Returns 0.0 if all curves are flat (output insensitive to src1).
    """
    if len(curves) < 2:
        return 1.0

    all_out = [v for c in curves for v in c['output_values']]
    out_min = np.min(all_out)
    out_max = np.max(all_out)
    out_range = out_max - out_min

    if out_range < 1e-9:
        return 0.0

    # Check if all curves are flat relative to the global range
    all_flat = all(
        np.std(np.array(c['output_values'])) / out_range < 0.05
        for c in curves
        if len(c['output_values']) > 1
    )
    if all_flat:
        return 0.0

    normalised = [(np.array(c['output_values']) - out_min) / out_range
                  for c in curves]

    max_diff = 0.0
    for i in range(len(normalised)):
        for j in range(i + 1, len(normalised)):
            diff = np.abs(normalised[i] - normalised[j])
            max_diff = max(max_diff, np.max(diff))

    return max_diff
