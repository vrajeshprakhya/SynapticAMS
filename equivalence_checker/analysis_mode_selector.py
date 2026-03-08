#!/usr/bin/env python3
"""
analysis_mode_selector.py

Automatically determines which analyses (DC, AC, Transient) are needed
based on circuit topology and component types.

Strategy:
1. Parse netlist to identify component types
2. Detect reactive elements (capacitors, inductors)
3. Identify feedback loops
4. Analyze circuit structure
5. Recommend appropriate analysis modes
"""

import re
from typing import List, Set, Dict
from dataclasses import dataclass


@dataclass
class CircuitCharacteristics:
    """Detected circuit characteristics"""
    has_capacitors: bool
    has_inductors: bool
    has_feedback: bool
    has_high_gain: bool
    num_reactive_elements: int
    num_poles_estimate: int
    has_differential_pair: bool
    has_current_mirror: bool
    circuit_type: str  # 'purely_resistive', 'single_pole', 'multi_pole', 'resonant', etc.


class AnalysisModeSelector:
    """
    Determines required analysis modes based on circuit topology
    """

    def __init__(self):
        pass

    def determine_analysis_modes(self, netlist: str, block_info: Dict = None) -> List[str]:
        """
        Automatically determine which analyses are needed

        Args:
            netlist: SPICE netlist
            block_info: Block metadata (optional)

        Returns:
            List of analysis modes: ['dc'], ['dc', 'ac'], or ['dc', 'ac', 'tran']
        """
        # Analyze circuit characteristics
        characteristics = self._analyze_circuit(netlist, block_info)

        # Determine required analyses
        modes = self._select_analyses(characteristics)

        return modes

    def _analyze_circuit(self, netlist: str, block_info: Dict = None) -> CircuitCharacteristics:
        """
        Analyze circuit topology and components
        """
        # Detect component types
        has_caps = self._has_capacitors(netlist)
        has_inds = self._has_inductors(netlist)

        # Count reactive elements
        num_caps = self._count_capacitors(netlist)
        num_inds = self._count_inductors(netlist)
        num_reactive = num_caps + num_inds

        # Estimate number of poles (very rough: ~1 pole per capacitor)
        num_poles = num_caps + num_inds

        # Detect circuit patterns
        has_feedback = self._detect_feedback(netlist, block_info)
        has_diff_pair = self._detect_differential_pair(netlist, block_info)
        has_current_mirror = self._detect_current_mirror(netlist, block_info)
        has_high_gain = self._detect_high_gain(netlist, block_info)

        # Classify circuit type
        circuit_type = self._classify_circuit_type(
            has_caps, has_inds, num_reactive, has_feedback
        )

        return CircuitCharacteristics(
            has_capacitors=has_caps,
            has_inductors=has_inds,
            has_feedback=has_feedback,
            has_high_gain=has_high_gain,
            num_reactive_elements=num_reactive,
            num_poles_estimate=num_poles,
            has_differential_pair=has_diff_pair,
            has_current_mirror=has_current_mirror,
            circuit_type=circuit_type
        )

    def _select_analyses(self, char: CircuitCharacteristics) -> List[str]:
        """
        Select appropriate analyses based on circuit characteristics

        Decision tree:
        1. DC always included (baseline)
        2. AC if has reactive elements OR feedback
        3. Transient if has multiple reactive elements OR resonant
        """
        modes = ['dc']  # DC always included

        # Add AC analysis if:
        if (char.has_capacitors or char.has_inductors or
            char.has_feedback or char.has_high_gain):
            modes.append('ac')

        # Add Transient analysis if:
        if (char.num_reactive_elements >= 2 or  # Multiple reactive elements
            char.circuit_type in ['resonant', 'oscillator', 'filter'] or
            char.has_inductors):  # Inductors always need transient (ringing)
            modes.append('tran')

        # Special cases based on circuit type
        if char.circuit_type == 'purely_resistive':
            # DC only is sufficient
            modes = ['dc']

        elif char.circuit_type == 'single_pole':
            # DC + AC to check bandwidth
            modes = ['dc', 'ac']

        elif char.circuit_type == 'multi_pole':
            # DC + AC for frequency response, might need transient
            if char.num_poles_estimate >= 3:
                modes = ['dc', 'ac', 'tran']
            else:
                modes = ['dc', 'ac']

        elif char.circuit_type in ['resonant', 'oscillator']:
            # All three needed
            modes = ['dc', 'ac', 'tran']

        elif char.circuit_type == 'filter':
            # AC is most important, but DC and transient also useful
            modes = ['dc', 'ac', 'tran']

        return modes

    def _has_capacitors(self, netlist: str) -> bool:
        """Check if netlist contains capacitors"""
        for line in netlist.split('\n'):
            line = line.strip()
            if line and not line.startswith('*') and not line.startswith('.'):
                if line[0].upper() == 'C':
                    return True
        return False

    def _has_inductors(self, netlist: str) -> bool:
        """Check if netlist contains inductors"""
        for line in netlist.split('\n'):
            line = line.strip()
            if line and not line.startswith('*') and not line.startswith('.'):
                if line[0].upper() == 'L':
                    return True
        return False

    def _count_capacitors(self, netlist: str) -> int:
        """Count number of capacitors"""
        count = 0
        for line in netlist.split('\n'):
            line = line.strip()
            if line and not line.startswith('*') and not line.startswith('.'):
                if line[0].upper() == 'C':
                    count += 1
        return count

    def _count_inductors(self, netlist: str) -> int:
        """Count number of inductors"""
        count = 0
        for line in netlist.split('\n'):
            line = line.strip()
            if line and not line.startswith('*') and not line.startswith('.'):
                if line[0].upper() == 'L':
                    count += 1
        return count

    def _detect_feedback(self, netlist: str, block_info: Dict = None) -> bool:
        """
        Detect feedback loops (heuristic)

        Indicators:
        - Output node connects back to input
        - Capacitor between output and input (Miller compensation)
        - Resistor feedback network
        """
        # Simple heuristic: look for components connecting output to gate/input
        # More sophisticated: build graph and detect cycles

        # Check block_info for feedback indicator
        if block_info and 'feedback' in block_info.get('behavior_class', '').lower():
            return True

        # Check for Miller capacitor pattern (Cxx out in)
        for line in netlist.split('\n'):
            line = line.strip().lower()
            if line and not line.startswith('*') and not line.startswith('.'):
                if line[0] == 'c':
                    tokens = re.split(r'\s+', line)
                    if len(tokens) >= 3:
                        # Check if connects output-ish to input-ish nodes
                        if ('out' in tokens[1] and 'in' in tokens[2]) or \
                           ('out' in tokens[2] and 'in' in tokens[1]):
                            return True

        return False

    def _detect_differential_pair(self, netlist: str, block_info: Dict = None) -> bool:
        """Detect differential pair topology"""
        if block_info:
            behavior = block_info.get('behavior_class', '').lower()
            if 'differential' in behavior:
                return True

        # Look for matched transistor pairs
        # Heuristic: Two transistors with same size and shared source/tail
        return False

    def _detect_current_mirror(self, netlist: str, block_info: Dict = None) -> bool:
        """Detect current mirror topology"""
        if block_info:
            behavior = block_info.get('behavior_class', '').lower()
            if 'mirror' in behavior or 'current_mirror' in behavior:
                return True

        # Look for diode-connected transistor + mirror transistor
        return False

    def _detect_high_gain(self, netlist: str, block_info: Dict = None) -> bool:
        """
        Detect high-gain stages

        Indicators:
        - Multiple cascaded amplifier stages
        - Cascode topology
        - Feedback amplifier
        """
        # Simple heuristic: count number of active devices
        num_mosfets = 0
        num_bjts = 0

        for line in netlist.split('\n'):
            line = line.strip()
            if line and not line.startswith('*') and not line.startswith('.'):
                if line[0].upper() == 'M':
                    num_mosfets += 1
                elif line[0].upper() == 'Q':
                    num_bjts += 1

        # High gain if multiple stages (heuristic: >4 transistors)
        return (num_mosfets + num_bjts) > 4

    def _classify_circuit_type(self, has_caps: bool, has_inds: bool,
                                num_reactive: int, has_feedback: bool) -> str:
        """
        Classify circuit type based on components
        """
        if not has_caps and not has_inds:
            return 'purely_resistive'

        elif has_caps and not has_inds and num_reactive == 1:
            return 'single_pole'

        elif has_caps and not has_inds and num_reactive >= 2:
            if has_feedback:
                return 'multi_pole'  # Could be multi-stage amplifier
            else:
                return 'filter'  # Likely RC filter

        elif has_inds and has_caps:
            if num_reactive >= 2:
                return 'resonant'  # LC resonant circuit
            else:
                return 'filter'

        elif has_inds and not has_caps:
            return 'inductive'

        else:
            return 'unknown'


# Convenience function
def select_analysis_modes(netlist: str, block_info: Dict = None) -> List[str]:
    """
    Convenience function to determine required analysis modes

    Returns:
        List of modes: e.g., ['dc', 'ac'] or ['dc', 'ac', 'tran']
    """
    selector = AnalysisModeSelector()
    return selector.determine_analysis_modes(netlist, block_info)


# Test cases
if __name__ == "__main__":
    print("=" * 70)
    print("ANALYSIS MODE SELECTOR - TEST CASES")
    print("=" * 70)

    # Test Case 1: Purely resistive (differential pair without caps)
    netlist_resistive = """
    * Differential pair (no caps)
    M1 out1 inp tail 0 NMOS W=20u L=1u
    M2 out2 inn tail 0 NMOS W=20u L=1u
    M3 tail bias 0 0 NMOS W=40u L=1u
    RD1 vdd out1 10k
    RD2 vdd out2 10k
    """

    modes = select_analysis_modes(netlist_resistive, {'behavior_class': 'differential'})
    print(f"\nTest 1: Differential Pair (No Caps)")
    print(f"  Recommended analyses: {modes}")
    print(f"  Expected: ['dc']")

    # Test Case 2: Single pole amplifier
    netlist_single_pole = """
    * Common source amplifier with load cap
    M1 out in 0 0 NMOS W=20u L=1u
    RD vdd out 10k
    CL out 0 1pF
    """

    modes = select_analysis_modes(netlist_single_pole)
    print(f"\nTest 2: Single-Pole Amplifier")
    print(f"  Recommended analyses: {modes}")
    print(f"  Expected: ['dc', 'ac']")

    # Test Case 3: Multi-stage amplifier with compensation
    netlist_multi_stage = """
    * Two-stage opamp with Miller compensation
    M1 mid inp tail 0 NMOS W=20u L=1u
    M2 out inn tail 0 NMOS W=20u L=1u
    M3 tail bias 0 0 NMOS W=40u L=1u
    M4 out mid vdd vdd PMOS W=50u L=1u
    RD vdd mid 10k
    CL out 0 5pF
    CC out mid 1pF
    """

    modes = select_analysis_modes(netlist_multi_stage)
    print(f"\nTest 3: Two-Stage OpAmp with Miller Compensation")
    print(f"  Recommended analyses: {modes}")
    print(f"  Expected: ['dc', 'ac'] or ['dc', 'ac', 'tran']")

    # Test Case 4: LC filter (resonant)
    netlist_lc_filter = """
    * LC bandpass filter
    Vin in 0 AC 1
    L1 in mid 10uH
    C1 mid 0 100pF
    L2 mid out 10uH
    C2 out 0 100pF
    RL out 0 50
    """

    modes = select_analysis_modes(netlist_lc_filter)
    print(f"\nTest 4: LC Bandpass Filter")
    print(f"  Recommended analyses: {modes}")
    print(f"  Expected: ['dc', 'ac', 'tran']")

    print("\n" + "=" * 70)
