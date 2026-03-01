#!/usr/bin/env python3
"""
SPICE Netlist Flattening Tool

This tool takes a hierarchical SPICE netlist with subcircuit definitions
and flattens it by replacing all subcircuit instances with their actual
contents, properly renaming nodes and devices to avoid conflicts.
"""

import re
import sys
import os
from typing import Dict, List, Tuple, Set


class SubcktDefinition:
    """Represents a subcircuit definition"""
    def __init__(self, name: str, ports: List[str], lines: List[str]):
        self.name = name
        self.ports = ports
        self.lines = lines  # Lines inside the subcircuit (excluding .SUBCKT and .ENDS)

    def __repr__(self):
        return f"Subckt({self.name}, ports={self.ports}, {len(self.lines)} lines)"


class SpiceFlattener:
    def __init__(self):
        self.subcircuits: Dict[str, SubcktDefinition] = {}
        self.top_level_lines: List[str] = []
        self.included_files: Set[str] = set()  # Track processed files
        self.base_dir: str = ""  # Base directory for resolving relative paths

    def _process_line_continuation(self, raw_lines: List[str]) -> List[str]:
        """
        Process SPICE 3f5 line continuation.

        Lines starting with '+' in column 1 continue the previous line.
        SPICE reads from column 2 onwards (index 1).

        Example:
            .SUBCKT LONG A B
            + C D
        Becomes:
            .SUBCKT LONG A B C D
        """
        processed = []
        i = 0

        while i < len(raw_lines):
            line = raw_lines[i].rstrip()

            # Check if next line is a continuation
            while i + 1 < len(raw_lines) and len(raw_lines[i + 1]) > 0 and raw_lines[i + 1][0] == '+':
                i += 1
                # Append from column 2 onwards (index 1)
                continuation = raw_lines[i][1:].rstrip() if len(raw_lines[i]) > 1 else ""
                line = line + ' ' + continuation

            processed.append(line)
            i += 1

        return processed

    def parse_netlist(self, filename: str, is_top_level: bool = True):
        """Parse a SPICE netlist file"""
        # Resolve to absolute path
        abs_filename = os.path.abspath(filename)

        # Check if already included (avoid circular includes)
        if abs_filename in self.included_files:
            return

        self.included_files.add(abs_filename)

        # Set base directory for resolving relative paths
        if is_top_level:
            self.base_dir = os.path.dirname(abs_filename)

        # Read file
        try:
            with open(abs_filename, 'r') as f:
                raw_lines = f.readlines()
        except FileNotFoundError:
            print(f"Warning: Could not find file: {abs_filename}")
            return

        # Process line continuation (SPICE 3f5 feature)
        # Lines starting with '+' in column 1 continue previous line from column 2
        lines = self._process_line_continuation(raw_lines)

        i = 0
        while i < len(lines):
            line = lines[i].rstrip()

            # Skip comment lines (SPICE 3f5 features):
            # 1. Lines starting with '*'
            # 2. Lines starting with whitespace (leading whitespace = comment)
            if line and (line[0] == '*' or line[0].isspace()):
                # Keep comments if processing top-level file
                if is_top_level:
                    self.top_level_lines.append(line)
                i += 1
                continue

            line_upper = line.upper().strip()

            # Check if this is a subcircuit definition
            if line_upper.startswith('.SUBCKT'):
                subckt, end_idx = self._parse_subcircuit(lines, i)
                self.subcircuits[subckt.name] = subckt
                i = end_idx + 1

            # Check for .INCLUDE statement
            elif line_upper.startswith('.INCLUDE') or line_upper.startswith('.INC'):
                include_file = self._parse_include(line)
                if include_file:
                    self._process_include(include_file, abs_filename)
                i += 1

            # Check for .LIB statement
            elif line_upper.startswith('.LIB'):
                lib_file, section = self._parse_lib(line)
                if lib_file:
                    self._process_lib(lib_file, section, abs_filename)
                i += 1

            else:
                # Top-level line (only save if processing top-level file)
                if is_top_level:
                    self.top_level_lines.append(line)
                i += 1

    def _parse_subcircuit(self, lines: List[str], start_idx: int) -> Tuple[SubcktDefinition, int]:
        """Parse a subcircuit definition starting at start_idx"""
        header = lines[start_idx].strip()

        # Parse .SUBCKT line: .SUBCKT name port1 port2 ...
        tokens = header.split()
        if len(tokens) < 2:
            raise ValueError(f"Invalid .SUBCKT line: {header}")

        subckt_name = tokens[1]
        ports = tokens[2:]  # All remaining tokens are ports

        # Find matching .ENDS
        subckt_lines = []
        i = start_idx + 1
        depth = 1

        while i < len(lines) and depth > 0:
            line = lines[i].rstrip()

            if line.upper().startswith('.SUBCKT'):
                depth += 1
            elif line.upper().startswith('.ENDS'):
                depth -= 1
                if depth == 0:
                    break

            if depth > 0:
                # Skip comment lines (SPICE 3f5):
                # - Lines starting with '*'
                # - Lines starting with whitespace (leading whitespace = comment)
                if not line or line[0] == '*' or (line and line[0].isspace()):
                    # Keep comments for context
                    subckt_lines.append(line)
                else:
                    subckt_lines.append(line)

            i += 1

        return SubcktDefinition(subckt_name, ports, subckt_lines), i

    def _parse_include(self, line: str) -> str:
        """Parse .INCLUDE statement and return the filename"""
        # Format: .INCLUDE "filename" or .INCLUDE 'filename' or .INCLUDE filename
        line_stripped = line.strip()

        # Remove .INCLUDE or .INC keyword
        if line_stripped.upper().startswith('.INCLUDE'):
            filename_part = line_stripped[8:].strip()
        elif line_stripped.upper().startswith('.INC'):
            filename_part = line_stripped[4:].strip()
        else:
            return None

        # Remove quotes if present
        filename = filename_part.strip('\'"')

        return filename if filename else None

    def _parse_lib(self, line: str) -> Tuple[str, str]:
        """
        Parse .LIB statement and return (filename, section_name)
        Format: .LIB 'filename' [section]
        """
        line_stripped = line.strip()

        # Remove .LIB keyword
        if not line_stripped.upper().startswith('.LIB'):
            return None, None

        remainder = line_stripped[4:].strip()

        # Check for quoted filename
        filename = None
        section = None

        if remainder.startswith("'") or remainder.startswith('"'):
            # Extract quoted filename
            quote_char = remainder[0]
            end_quote = remainder.find(quote_char, 1)
            if end_quote > 0:
                filename = remainder[1:end_quote]
                # Check for section name after the closing quote
                after_quote = remainder[end_quote + 1:].strip()
                if after_quote:
                    section = after_quote.strip('\'"')
        else:
            # No quotes - split by whitespace
            parts = remainder.split()
            if parts:
                filename = parts[0].strip('\'"')
                if len(parts) > 1:
                    section = parts[1].strip('\'"')

        return filename, section

    def _resolve_path(self, filename: str, current_file: str) -> str:
        """
        Resolve a filename relative to current file's directory.

        Resolution order:
        1. If absolute path - use as-is
        2. Try relative to current file's directory (standard SPICE behavior)
        3. Try relative to base directory (top-level netlist directory)
        """
        if os.path.isabs(filename):
            return filename

        # Try relative to current file's directory
        current_dir = os.path.dirname(current_file)
        resolved = os.path.join(current_dir, filename)
        if os.path.exists(resolved):
            return resolved

        # Try relative to base directory
        resolved = os.path.join(self.base_dir, filename)
        if os.path.exists(resolved):
            return resolved

        # Return as-is and let file open fail later with better error message
        return filename

    def _process_include(self, include_file: str, current_file: str):
        """Process a .INCLUDE file"""
        resolved_path = self._resolve_path(include_file, current_file)
        print(f"  Including: {include_file} -> {resolved_path}")
        self.parse_netlist(resolved_path, is_top_level=False)

    def _process_lib(self, lib_file: str, section: str, current_file: str):
        """Process a .LIB file"""
        resolved_path = self._resolve_path(lib_file, current_file)

        if section:
            print(f"  Loading library: {lib_file} (section: {section}) -> {resolved_path}")
        else:
            print(f"  Loading library: {lib_file} -> {resolved_path}")

        # For .LIB files, we need to handle sections
        if section:
            self._parse_lib_file_with_section(resolved_path, section)
        else:
            # No section specified - parse entire file
            self.parse_netlist(resolved_path, is_top_level=False)

    def _parse_lib_file_with_section(self, filename: str, section: str):
        """Parse a .LIB file and extract only the specified section"""
        abs_filename = os.path.abspath(filename)

        # Check if already included
        if abs_filename in self.included_files:
            return

        self.included_files.add(abs_filename)

        try:
            with open(abs_filename, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"Warning: Could not find library file: {abs_filename}")
            return

        # Find the section
        in_section = False
        section_upper = section.upper()
        i = 0

        while i < len(lines):
            line = lines[i].rstrip()
            line_upper = line.upper().strip()

            # Check for .LIB SECTION_NAME
            if line_upper.startswith('.LIB') and section_upper in line_upper:
                in_section = True
                i += 1
                continue

            # Check for .ENDL (end of library section)
            if line_upper.startswith('.ENDL'):
                if in_section:
                    break
                i += 1
                continue

            # Process lines within the section
            if in_section:
                if line_upper.startswith('.SUBCKT'):
                    subckt, end_idx = self._parse_subcircuit(lines, i)
                    self.subcircuits[subckt.name] = subckt
                    i = end_idx + 1
                elif line_upper.startswith('.INCLUDE') or line_upper.startswith('.INC'):
                    include_file = self._parse_include(line)
                    if include_file:
                        self._process_include(include_file, abs_filename)
                    i += 1
                else:
                    i += 1
            else:
                i += 1

    def flatten(self) -> List[str]:
        """Flatten the netlist by resolving all subcircuit instances"""
        flattened = []

        for line in self.top_level_lines:
            if self._is_subcircuit_instance(line):
                # Flatten this instance
                flattened_instance = self._flatten_instance(line, prefix="")
                flattened.extend(flattened_instance)
            else:
                flattened.append(line)

        return flattened

    def _is_subcircuit_instance(self, line: str) -> bool:
        """Check if a line is a subcircuit instance (starts with X)"""
        stripped = line.strip()
        if not stripped or stripped.startswith('*'):
            return False
        return stripped.upper().startswith('X')

    def _flatten_instance(self, instance_line: str, prefix: str, depth: int = 0) -> List[str]:
        """
        Flatten a single subcircuit instance.

        Args:
            instance_line: The X... instance line
            prefix: Hierarchical prefix for unique naming
            depth: Recursion depth (for debugging)

        Returns:
            List of flattened lines
        """
        # Parse instance line: Xname node1 node2 ... subckt_name [params]
        tokens = instance_line.split()

        if len(tokens) < 2:
            return [instance_line]  # Return as-is if can't parse

        instance_name = tokens[0]  # X0, X1, etc.

        # Find the subcircuit name (last token that matches a known subcircuit)
        subckt_name = None
        subckt_idx = -1

        for i in range(len(tokens) - 1, 0, -1):
            if tokens[i] in self.subcircuits:
                subckt_name = tokens[i]
                subckt_idx = i
                break

        if not subckt_name:
            # Subcircuit not found, return original line with comment
            return [f"{instance_line}  * WARNING: Subcircuit definition not found"]

        # Nodes connected to this instance
        connected_nodes = tokens[1:subckt_idx]

        # Parameters (everything after subcircuit name)
        params = tokens[subckt_idx + 1:] if subckt_idx + 1 < len(tokens) else []

        # Get the subcircuit definition
        subckt = self.subcircuits[subckt_name]

        # Check port count
        if len(connected_nodes) != len(subckt.ports):
            return [f"{instance_line}  * ERROR: Port count mismatch ({len(connected_nodes)} vs {len(subckt.ports)})"]

        # Create port mapping: subcircuit port name -> actual net name
        port_map = dict(zip(subckt.ports, connected_nodes))

        # Create unique prefix for this instance
        if prefix:
            unique_prefix = f"{prefix}_{instance_name}"
        else:
            unique_prefix = instance_name

        # Flatten the subcircuit
        flattened = []
        flattened.append(f"* Flattened instance: {instance_line}")
        flattened.append(f"* Begin subcircuit: {unique_prefix} ({subckt_name})")

        for subckt_line in subckt.lines:
            if self._is_subcircuit_instance(subckt_line):
                # Recursively flatten nested subcircuit
                nested_flattened = self._flatten_instance(subckt_line, unique_prefix, depth + 1)
                # Rename nodes in nested instance
                for nested_line in nested_flattened:
                    renamed_line = self._rename_nodes_in_line(nested_line, port_map, unique_prefix)
                    flattened.append(renamed_line)
            else:
                # Regular device or comment
                renamed_line = self._rename_line(subckt_line, port_map, unique_prefix)
                flattened.append(renamed_line)

        flattened.append(f"* End subcircuit: {unique_prefix}")

        return flattened

    def _rename_line(self, line: str, port_map: Dict[str, str], prefix: str) -> str:
        """
        Rename devices and nodes in a line.

        - Device names get prefixed
        - Port nodes get replaced with actual connections
        - Internal nodes get prefixed
        - Model names are preserved (not renamed)
        """
        stripped = line.strip()

        # Handle comments (SPICE 3f5):
        # 1. Empty lines
        # 2. Lines starting with '*'
        # 3. Lines starting with whitespace (leading whitespace = comment)
        if not stripped or stripped.startswith('*'):
            return line

        # Check for leading whitespace comment (SPICE 3f5 feature)
        if line and line[0].isspace():
            return line

        # Handle continuation lines (lines starting with +)
        if stripped.startswith('+'):
            return line

        # Handle control statements (.INCLUDE, .LIB, etc.)
        if stripped.startswith('.'):
            return line

        tokens = line.split()
        if not tokens:
            return line

        # First token is device name - prefix it
        # IMPORTANT: Keep the device type letter first for SPICE compatibility
        device_name = tokens[0]
        device_type = device_name[0].upper()

        # If it's a device (not subcircuit instance), preserve device type at start
        if device_type in 'MQDRCLVIEGFHKBSTU' and not device_name.upper().startswith('X'):
            # Format: M_prefix_originalname
            if prefix:
                new_device_name = f"{device_type}_{prefix}_{device_name[1:]}"
            else:
                new_device_name = device_name
        else:
            # For subcircuit instances or unknown, use regular prefixing
            new_device_name = f"{prefix}_{device_name}" if prefix else device_name

        # Process remaining tokens (nodes, model, and parameters)
        new_tokens = [new_device_name]

        # Determine device type and node count
        device_type = device_name[0].upper()
        node_count, model_idx = self._get_device_info(device_type, tokens)

        # Rename nodes (tokens[1:node_count+1])
        for i in range(1, min(node_count + 1, len(tokens))):
            node = tokens[i]
            new_node = self._rename_node(node, port_map, prefix)
            new_tokens.append(new_node)

        # Add model name and remaining tokens (parameters) as-is
        for i in range(node_count + 1, len(tokens)):
            new_tokens.append(tokens[i])

        return ' '.join(new_tokens)

    def _get_device_info(self, device_type: str, tokens: List[str]) -> Tuple[int, int]:
        """
        Get the number of nodes and model name index for a device type.

        Returns:
            (node_count, model_idx) where model_idx is -1 if no model name
        """
        # Common SPICE device types and their node counts
        # Format: device_type -> (node_count, has_model_name)
        device_info = {
            'M': (4, True),   # MOSFET: D G S B model
            'Q': (3, True),   # BJT: C B E model
            'D': (2, True),   # Diode: + - model
            'R': (2, False),  # Resistor: + -
            'C': (2, False),  # Capacitor: + -
            'L': (2, False),  # Inductor: + -
            'V': (2, False),  # Voltage source: + -
            'I': (2, False),  # Current source: + -
            'E': (4, False),  # VCVS: out+ out- in+ in-
            'F': (4, False),  # CCCS: out+ out- vsense
            'G': (4, False),  # VCCS: out+ out- in+ in-
            'H': (4, False),  # CCVS: out+ out- vsense
            'K': (2, False),  # Mutual inductance
        }

        if device_type in device_info:
            node_count, has_model = device_info[device_type]
            model_idx = node_count + 1 if has_model else -1
            return node_count, model_idx

        # Unknown device type - use heuristic
        # Find first token with '=' as start of parameters
        for i in range(1, len(tokens)):
            if '=' in tokens[i]:
                return i - 1, -1

        # If no parameters found, assume all remaining are nodes
        return len(tokens) - 1, -1

    def _rename_nodes_in_line(self, line: str, port_map: Dict[str, str], prefix: str) -> str:
        """Rename nodes in an already-flattened line (for nested instances)"""
        # For nested instances:
        # - Device names are already prefixed
        # - Nodes need to be mapped/prefixed
        # - Model names should not be renamed
        stripped = line.strip()

        if not stripped or stripped.startswith('*') or stripped.startswith('.'):
            return line

        tokens = line.split()
        if not tokens:
            return line

        # Determine device type and node count
        # Device name is already prefixed (e.g., X_DFF1_X1_M1)
        # Extract original type by finding the device letter after the last prefix
        device_name = tokens[0]
        device_type = self._extract_device_type(device_name)

        if device_type:
            node_count, model_idx = self._get_device_info(device_type, tokens)
        else:
            # Fallback: find parameters
            node_count = len(tokens) - 1
            for i in range(1, len(tokens)):
                if '=' in tokens[i]:
                    node_count = i - 1
                    break

        # Rename nodes using the same logic as _rename_node
        new_tokens = [tokens[0]]  # Keep device name (already prefixed)

        for i in range(1, min(node_count + 1, len(tokens))):
            node = tokens[i]
            # Apply port mapping and prefixing (but not to model names)
            new_node = self._rename_node(node, port_map, prefix)
            new_tokens.append(new_node)

        # Keep model name and parameters as-is
        for i in range(node_count + 1, len(tokens)):
            new_tokens.append(tokens[i])

        return ' '.join(new_tokens)

    def _rename_node(self, node: str, port_map: Dict[str, str], prefix: str) -> str:
        """
        Rename a single node.

        Priority:
        1. If node is in port_map, use the mapped value (external connection)
        2. If node is a global node (GND, VDD, 0), keep as-is
        3. Otherwise, prefix it to make it unique
        """
        # Check if it's a port (should be mapped to external net)
        if node in port_map:
            return port_map[node]

        # Check if it's a global node
        if node.upper() in ['GND', 'VDD', 'VSS', 'VDDA', 'VSSA', '0']:
            return node

        # Check if it's already prefixed (from nested flattening)
        # Don't double-prefix

        # Internal node - prefix it
        return f"{prefix}_{node}"

    def _extract_device_type(self, device_name: str) -> str:
        """
        Extract the device type from a (possibly prefixed) device name.

        Examples:
            M1 -> M
            X_DFF1_X1_M1 -> M
            R_BIAS -> R
        """
        # Common SPICE device type letters
        device_letters = 'MQDRCLVIEGFHKXBSTU'

        # Try to find device type by looking for pattern: <prefix>_<LETTER><digits>
        # Work backwards from the end
        parts = device_name.split('_')
        if parts:
            last_part = parts[-1]
            # First character of last part should be the device type
            if last_part and last_part[0].upper() in device_letters:
                return last_part[0].upper()

        # Fallback: first alphabetic character
        for char in device_name:
            if char.isalpha() and char.upper() in device_letters:
                return char.upper()

        return None

    def _looks_like_param(self, token: str) -> bool:
        """Heuristic to determine if a token is a parameter"""
        # Common SPICE parameters
        param_keywords = ['L', 'W', 'M', 'MULT', 'R', 'C', 'V', 'I',
                         'AD', 'AS', 'PD', 'PS', 'NRD', 'NRS']

        upper = token.upper()

        # Check if it starts with a parameter keyword
        for kw in param_keywords:
            if upper.startswith(kw + '='):
                return True

        # Check for numeric value (might be a parameter value)
        # But be careful - node names can be numeric too
        # This is a weak heuristic

        return False

    def write_flattened(self, output_filename: str):
        """Write the flattened netlist to a file"""
        flattened_lines = self.flatten()

        with open(output_filename, 'w') as f:
            for line in flattened_lines:
                f.write(line + '\n')


def main():
    if len(sys.argv) < 2:
        print("Usage: python spice_flatten.py <input_netlist> [output_netlist]")
        print("\nThis tool flattens a hierarchical SPICE netlist by inlining all")
        print("subcircuit definitions.")
        sys.exit(1)

    input_file = sys.argv[1]

    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        # Default output filename
        if input_file.endswith('.sp') or input_file.endswith('.spice'):
            output_file = input_file.rsplit('.', 1)[0] + '_flat.' + input_file.rsplit('.', 1)[1]
        else:
            output_file = input_file + '_flat'

    print(f"Flattening SPICE netlist: {input_file}")

    flattener = SpiceFlattener()

    try:
        flattener.parse_netlist(input_file)
        print(f"Found {len(flattener.subcircuits)} subcircuit definitions:")
        for name, subckt in flattener.subcircuits.items():
            print(f"  - {name}: {len(subckt.ports)} ports, {len(subckt.lines)} lines")

        flattener.write_flattened(output_file)
        print(f"\nFlattened netlist written to: {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
