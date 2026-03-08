#!/usr/bin/env python3
"""
analysis_mode_selector.py

Automatically determines which analyses (DC, AC, Transient) are needed
based on circuit topology and component types.

Strategy:
1. Parse netlist to identify component types
2. Detect reactive elements (capacitors, inductors)
3. Identify feedback loops
4. Analyse circuit structure
5. Recommend appropriate analysis modes
"""

import re
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class CircuitCharacteristics:
    """Detected circuit characteristics."""
    has_capacitors: bool
    has_inductors: bool
    has_feedback: bool
    has_high_gain: bool
    num_reactive_elements: int
    num_poles_estimate: int
    has_differential_pair: bool
    has_current_mirror: bool
    circuit_type: str   # 'purely_resistive' | 'single_pole' | 'multi_pole' |
                        # 'resonant' | 'oscillator' | 'filter' | 'inductive' | 'unknown'


class AnalysisModeSelector:
    """Determines required analysis modes based on circuit topology."""

    def determine_analysis_modes(self, netlist: str,
                                 block_info: Dict = None) -> List[str]:
        """
        Return a list of required analysis modes for the given netlist.

        Returns one of:
            ['dc']
            ['dc', 'ac']
            ['dc', 'ac', 'tran']
        """
        char  = self._analyze_circuit(netlist, block_info)
        return self._select_analyses(char)

    def _analyze_circuit(self, netlist: str,
                         block_info: Dict = None) -> CircuitCharacteristics:
        has_caps = self._has_capacitors(netlist)
        has_inds = self._has_inductors(netlist)
        num_caps = self._count_capacitors(netlist)
        num_inds = self._count_inductors(netlist)
        num_reactive = num_caps + num_inds

        return CircuitCharacteristics(
            has_capacitors      = has_caps,
            has_inductors       = has_inds,
            has_feedback        = self._detect_feedback(netlist, block_info),
            has_high_gain       = self._detect_high_gain(netlist, block_info),
            num_reactive_elements = num_reactive,
            num_poles_estimate  = num_caps + num_inds,
            has_differential_pair = self._detect_differential_pair(netlist, block_info),
            has_current_mirror  = self._detect_current_mirror(netlist, block_info),
            circuit_type        = self._classify_circuit_type(
                has_caps, has_inds, num_reactive,
                self._detect_feedback(netlist, block_info)),
        )

    def _select_analyses(self, char: CircuitCharacteristics) -> List[str]:
        modes = ['dc']

        if (char.has_capacitors or char.has_inductors
                or char.has_feedback or char.has_high_gain):
            modes.append('ac')

        if (char.num_reactive_elements >= 2
                or char.circuit_type in ('resonant', 'oscillator', 'filter')
                or char.has_inductors):
            modes.append('tran')

        # Override by circuit type
        if char.circuit_type == 'purely_resistive':
            return ['dc']
        if char.circuit_type == 'single_pole':
            return ['dc', 'ac']
        if char.circuit_type == 'multi_pole':
            return ['dc', 'ac', 'tran'] if char.num_poles_estimate >= 3 else ['dc', 'ac']
        if char.circuit_type in ('resonant', 'oscillator', 'filter'):
            return ['dc', 'ac', 'tran']

        return modes

    # ── component detection helpers ──────────────────────────────────────

    def _has_capacitors(self, netlist: str) -> bool:
        return self._count_capacitors(netlist) > 0

    def _has_inductors(self, netlist: str) -> bool:
        return self._count_inductors(netlist) > 0

    def _count_capacitors(self, netlist: str) -> int:
        return sum(1 for ln in netlist.split('\n')
                   if ln.strip() and not ln.strip().startswith(('*', '.'))
                   and ln.strip()[0].upper() == 'C')

    def _count_inductors(self, netlist: str) -> int:
        return sum(1 for ln in netlist.split('\n')
                   if ln.strip() and not ln.strip().startswith(('*', '.'))
                   and ln.strip()[0].upper() == 'L')

    def _detect_feedback(self, netlist: str, block_info: Dict = None) -> bool:
        if block_info and 'feedback' in block_info.get('behavior_class', '').lower():
            return True
        # Miller capacitor heuristic: C connecting 'out' node to 'in' node
        for ln in netlist.split('\n'):
            ln = ln.strip().lower()
            if ln and not ln.startswith(('*', '.')) and ln[0] == 'c':
                tokens = re.split(r'\s+', ln)
                if len(tokens) >= 3:
                    if (('out' in tokens[1] and 'in' in tokens[2])
                            or ('out' in tokens[2] and 'in' in tokens[1])):
                        return True
        return False

    def _detect_differential_pair(self, netlist: str,
                                   block_info: Dict = None) -> bool:
        if block_info:
            if 'differential' in block_info.get('behavior_class', '').lower():
                return True
        return False

    def _detect_current_mirror(self, netlist: str,
                                block_info: Dict = None) -> bool:
        if block_info:
            b = block_info.get('behavior_class', '').lower()
            if 'mirror' in b or 'current_mirror' in b:
                return True
        return False

    def _detect_high_gain(self, netlist: str, block_info: Dict = None) -> bool:
        """Heuristic: >4 transistors suggests a multi-stage / high-gain circuit."""
        count = sum(1 for ln in netlist.split('\n')
                    if ln.strip() and not ln.strip().startswith(('*', '.'))
                    and ln.strip()[0].upper() in ('M', 'Q'))
        return count > 4

    def _classify_circuit_type(self, has_caps: bool, has_inds: bool,
                                num_reactive: int,
                                has_feedback: bool) -> str:
        if not has_caps and not has_inds:
            return 'purely_resistive'
        if has_caps and not has_inds and num_reactive == 1:
            return 'single_pole'
        if has_caps and not has_inds and num_reactive >= 2:
            return 'multi_pole' if has_feedback else 'filter'
        if has_inds and has_caps and num_reactive >= 2:
            return 'resonant'
        if has_inds and has_caps:
            return 'filter'
        if has_inds:
            return 'inductive'
        return 'unknown'


def select_analysis_modes(netlist: str, block_info: Dict = None) -> List[str]:
    """Convenience wrapper around AnalysisModeSelector."""
    return AnalysisModeSelector().determine_analysis_modes(netlist, block_info)
