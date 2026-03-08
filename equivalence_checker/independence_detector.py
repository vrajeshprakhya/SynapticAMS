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
    Empirically test if two sources are independent using simulation

    Strategy:
    1. Sweep src1 while holding src2 at value_low
    2. Sweep src1 while holding src2 at value_high
    3. Compare transfer functions - if shape changes, they're coupled

    Args:
        netlist: SPICE netlist as string
        src1: First source name (e.g., "vin")
        src2: Second source name (e.g., "isrc")
        output_node: Output node to observe (e.g., "vout")
        runner: NgspiceRunner instance
        vdd: Supply voltage (for determining sweep ranges)
        coupling_threshold: Max normalized difference for independence (0.05 = 5%)
        n_test_points: Number of test values for src2 (default: 3 = low/mid/high)

    Returns:
        dict: {
            'coupled': bool,
            'sources': [src1, src2],
            'coupling_strength': float,  # 0.0 = independent, >0.05 = coupled
            'recommendation': str,       # '1D' or '2D'
            'test_details': dict         # Detailed test results
        }
    """
    # Find device names from node names (e.g., 'inn' → 'Vinn')
    src1_device = _find_source_device_name(netlist, src1)
    src2_device = _find_source_device_name(netlist, src2)

    # Determine if sources are voltage or current
    src1_type = _get_source_type(netlist, src1_device)
    src2_type = _get_source_type(netlist, src2_device)

    # Determine sweep range for src1
    src1_range = _determine_source_range(src1_type, vdd, netlist)
    src2_range = _determine_source_range(src2_type, vdd, netlist)

    # Generate test values for src2 (low, mid, high)
    src2_test_values = np.linspace(src2_range[0], src2_range[1], n_test_points)

    # Storage for transfer function curves
    curves = []

    # Run comparative sweeps
    for i, src2_value in enumerate(src2_test_values):
        # Modify netlist to set src2 to fixed value (use device name, not node name)
        netlist_modified = _set_source_dc_value(netlist, src2_device, src2_value)

        # DEBUG: Print modified line
        for line in netlist_modified.split('\n'):
            if src2_device.lower() in line.lower() and not line.strip().startswith('*'):
                print(f"      Modified: {line.strip()}")

        # Sweep src1
        sweep_params = {
            'sweep_var': src1,
            'start': src1_range[0],
            'stop': src1_range[1],
            'step': (src1_range[1] - src1_range[0]) / 20,  # 20 points
            'observe': [output_node]
        }

        try:
            results = runner.dc_sweep(netlist_modified, sweep_params)

            # Store the output curve
            if output_node in results:
                output_vals = results[output_node]
                curves.append({
                    'src2_value': src2_value,
                    'src1_values': results[src1],
                    'output_values': output_vals
                })

                # DEBUG: Print curve info
                if len(output_vals) > 0:
                    print(f"      Curve {i+1}: {src2}={src2_value:.3f} → output range [{output_vals.min():.3f}, {output_vals.max():.3f}]")
                else:
                    print(f"      Curve {i+1}: {src2}={src2_value:.3f} → NO DATA")
        except Exception as e:
            # If simulation fails, assume coupling (conservative approach)
            return {
                'coupled': True,
                'sources': [src1, src2],
                'coupling_strength': 1.0,
                'recommendation': '2D',
                'test_details': {
                    'error': f"Simulation failed: {e}",
                    'reason': 'simulation_failure'
                }
            }

    # Compare curves to detect coupling
    if len(curves) < 2:
        # Not enough data
        return {
            'coupled': True,
            'sources': [src1, src2],
            'coupling_strength': 1.0,
            'recommendation': '2D',
            'test_details': {'error': 'Insufficient simulation data'}
        }

    # Calculate coupling strength
    coupling_strength = _calculate_coupling_strength(curves)

    # Determine if coupled
    coupled = coupling_strength > coupling_threshold

    return {
        'coupled': coupled,
        'sources': [src1, src2],
        'coupling_strength': coupling_strength,
        'recommendation': '2D' if coupled else '1D',
        'test_details': {
            'n_curves': len(curves),
            'src2_test_values': src2_test_values.tolist(),
            'threshold': coupling_threshold,
            'src1_type': src1_type,
            'src2_type': src2_type
        }
    }


def _find_source_device_name(netlist, node_name):
    """
    Find the device name (e.g., 'Vinn') that connects to a given node (e.g., 'inn')

    Returns:
        str: Device name, or node_name if not found
    """
    for line in netlist.split('\n'):
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue

        tokens = re.split(r'\s+', line)
        if len(tokens) < 3:
            continue

        # Check if this is a V or I source
        if tokens[0][0].upper() not in ['V', 'I']:
            continue

        # Check if it connects to the node (node1 or node2)
        if tokens[1].lower() == node_name.lower() or tokens[2].lower() == node_name.lower():
            return tokens[0]  # Return device name

    # Not found - return node name as fallback
    return node_name


def _get_source_type(netlist, source_name):
    """
    Determine if source is voltage (V) or current (I)

    Args:
        source_name: Either device name (e.g., 'Vinn') or node name (e.g., 'inn')

    Returns:
        str: 'V' or 'I'
    """
    # First try to find by device name
    for line in netlist.split('\n'):
        line = line.strip()
        if not line or line.startswith('*') or line.startswith('.'):
            continue

        tokens = re.split(r'\s+', line)
        if len(tokens) < 1:
            continue

        # Check if this line defines the source by device name
        if tokens[0].lower() == source_name.lower():
            return tokens[0][0].upper()  # First character: V or I

    # Not found by device name - try to find device by node name
    device_name = _find_source_device_name(netlist, source_name)
    if device_name[0].upper() in ['V', 'I']:
        return device_name[0].upper()

    # Default: assume voltage source
    return 'V'


def _extract_all_currents_from_netlist(netlist):
    """
    Extract ALL current sources from netlist

    Args:
        netlist: SPICE netlist as string

    Returns:
        dict: {net_name: current_value} for all current sources
              Example: {'ibias1': 100e-6, 'ibias2': 10e-6, 'iref': 1e-3}
    """
    import re

    currents = {}

    for line in netlist.split('\n'):
        line = line.strip()

        # Skip comments and control lines
        if not line or line.startswith('*') or line.startswith('.'):
            continue

        # Look for current sources: Ixxx node1 node2 DC <value>
        if not line[0].upper() == 'I':
            continue

        # Parse: Ibias bias 0 DC 50uA
        tokens = re.split(r'\s+', line)
        if len(tokens) < 4:
            continue

        source_name = tokens[0]
        pos_node = tokens[1].lower()
        neg_node = tokens[2].lower()

        # Extract DC value
        match = re.search(r'DC\s+([\d.eE+-]+)\s*([uµnmkKMG]?)[Aa]?', line, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2) if len(match.groups()) > 1 and match.group(2) else ''

            # Convert to Amps
            if unit.lower() in ['u', 'µ']:
                value *= 1e-6
            elif unit.lower() == 'n':
                value *= 1e-9
            elif unit.lower() == 'm':
                value *= 1e-3
            elif unit.lower() == 'k':
                value *= 1e3
            elif unit.lower() in ['meg', 'g']:
                value *= 1e6

            # Filter out very small currents (< 1nA)
            if abs(value) > 1e-9:
                # Store by the non-ground node name
                if neg_node in ['0', 'gnd', 'ground']:
                    currents[pos_node] = abs(value)
                elif pos_node in ['0', 'gnd', 'ground']:
                    currents[neg_node] = abs(value)
                else:
                    # Both nodes are non-ground
                    currents[pos_node] = abs(value)

    return currents


def _extract_max_current_from_netlist(netlist):
    """
    Extract maximum current source value from netlist

    For multi-current circuits: returns maximum current value

    Args:
        netlist: SPICE netlist as string

    Returns:
        Maximum current in Amps (default 100µA if not found)
    """
    currents = _extract_all_currents_from_netlist(netlist)

    if not currents:
        return 100e-6  # Default: 100µA

    # Return maximum current (conservative approach)
    return max(currents.values())


def _determine_source_range(source_type, vdd, netlist=''):
    """
    Determine appropriate sweep range based on source type

    Args:
        source_type: 'V' or 'I'
        vdd: Supply voltage
        netlist: SPICE netlist (for extracting current ranges)

    Returns:
        tuple: (start, stop)
    """
    if source_type == 'V':
        # Voltage source: 0 to VDD
        return (0.0, vdd)
    else:  # Current source
        # Extract from netlist with 2× safety margin
        max_current = _extract_max_current_from_netlist(netlist)
        return (0.0, max_current * 2.0)


def _set_source_dc_value(netlist, source_name, dc_value):
    """
    Modify netlist to set a source's DC value

    Args:
        netlist: SPICE netlist as string
        source_name: Source name (e.g., "Isrc", "Vin")
        dc_value: New DC value

    Returns:
        str: Modified netlist
    """
    lines = []
    for line in netlist.split('\n'):
        stripped = line.strip()

        # Skip comments and control lines
        if not stripped or stripped.startswith('*') or stripped.startswith('.'):
            lines.append(line)
            continue

        tokens = re.split(r'\s+', stripped)
        if len(tokens) < 1:
            lines.append(line)
            continue

        # Check if this is the source we want to modify
        if tokens[0].lower() == source_name.lower():
            # Reconstruct source line with new DC value
            # Format: Vsrc node1 node2 DC value [AC value] [other...]
            source_type = tokens[0][0].upper()

            if len(tokens) >= 3:
                # Format DC value appropriately
                if source_type == 'V':
                    dc_str = f"{dc_value:.6f}"
                else:
                    # Current: format with engineering notation if small
                    if abs(dc_value) < 1e-3:
                        dc_str = f"{dc_value:.6e}"
                    else:
                        dc_str = f"{dc_value:.6f}"

                # Find and replace DC value in the line
                # Handle both "DC <value>" and bare value cases
                new_tokens = [tokens[0], tokens[1], tokens[2]]  # name, node1, node2

                # Look for DC keyword
                dc_idx = None
                for i in range(3, len(tokens)):
                    if tokens[i].upper() == 'DC':
                        dc_idx = i
                        break

                if dc_idx is not None:
                    # Replace DC value
                    new_tokens.append('DC')
                    new_tokens.append(dc_str)
                    # Preserve everything after DC value (like AC keyword)
                    if dc_idx + 2 < len(tokens):
                        new_tokens.extend(tokens[dc_idx + 2:])
                else:
                    # No explicit DC keyword - add it
                    new_tokens.append('DC')
                    new_tokens.append(dc_str)
                    # Preserve any remaining tokens (AC, etc.)
                    if len(tokens) > 3:
                        new_tokens.extend(tokens[3:])

                new_line = ' '.join(new_tokens)
                lines.append(new_line)
            else:
                lines.append(line)
        else:
            lines.append(line)

    return '\n'.join(lines)


def _calculate_coupling_strength(curves):
    """
    Calculate coupling strength by comparing transfer function curves

    Method:
    - Normalize all curves to [0, 1]
    - Calculate max point-wise difference between curves
    - High difference = strong coupling

    Args:
        curves: List of dicts with 'src1_values' and 'output_values'

    Returns:
        float: Coupling strength (0.0 = independent, >0.05 = coupled)
    """
    if len(curves) < 2:
        return 1.0  # Assume coupled if insufficient data

    # Extract output ranges for normalization
    all_outputs = []
    for curve in curves:
        all_outputs.extend(curve['output_values'])

    output_min = np.min(all_outputs)
    output_max = np.max(all_outputs)
    output_range = output_max - output_min

    if output_range < 1e-9:
        # Output doesn't change - no coupling detected
        return 0.0

    # CRITICAL: Check if all curves are flat (constant)
    # This detects the case where output depends on src2 but NOT on src1
    # (e.g., sweeping in2 while observing out1 that only depends on in1)
    all_flat = True
    for curve in curves:
        output_vals = np.array(curve['output_values'])
        # Calculate variance relative to range
        if len(output_vals) > 1:
            curve_variance = np.std(output_vals)
            relative_variance = curve_variance / output_range
            # If curve varies more than 5% of total range, it's not flat
            if relative_variance > 0.05:
                all_flat = False
                break

    if all_flat:
        # All curves are flat - output doesn't depend on swept variable (src1)
        # This means sources are independent (output depends on src2 but not src1)
        return 0.0

    # Normalize curves to [0, 1]
    normalized_curves = []
    for curve in curves:
        normalized = (np.array(curve['output_values']) - output_min) / output_range
        normalized_curves.append(normalized)

    # Calculate max difference between any two curves
    max_difference = 0.0
    for i in range(len(normalized_curves)):
        for j in range(i + 1, len(normalized_curves)):
            # Point-wise difference
            diff = np.abs(normalized_curves[i] - normalized_curves[j])
            max_diff_ij = np.max(diff)
            max_difference = max(max_difference, max_diff_ij)

    return max_difference


# Test function
if __name__ == "__main__":
    # Example test netlist with coupled sources
    test_netlist_coupled = """
* Current-feedback amplifier (coupled)
M1 out vin 0 0 NMOS W=20u L=1u
Isrc out 0 DC 0
Vin vin 0 DC 0
RD vdd out 10k
VDD vdd 0 DC 1.8
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

    # Example test netlist with independent sources
    test_netlist_independent = """
* Two independent stages
Vin in1 0 DC 0
M1 mid in1 0 0 NMOS W=10u L=1u
R1 vdd mid 10k

Isrc in2 0 DC 0
M2 out in2 0 0 NMOS W=10u L=1u
R2 vdd out 10k

VDD vdd 0 DC 1.8
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

    print("Independence Detector Module")
    print("=" * 70)
    print("\nThis module provides simulation-based independence testing.")
    print("To test, call test_source_independence() with NgspiceRunner instance.")
    print("\nExample usage:")
    print("  from ngspice_runner import NgspiceRunner")
    print("  from independence_detector import test_source_independence")
    print("  ")
    print("  runner = NgspiceRunner()")
    print("  result = test_source_independence(")
    print("      netlist, 'vin', 'isrc', 'out', runner")
    print("  )")
    print("  print(result['recommendation'])  # '1D' or '2D'")
