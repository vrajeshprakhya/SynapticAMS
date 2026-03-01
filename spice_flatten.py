#!/usr/bin/env python3
"""
SPICE Netlist Flattening — SynapticAMS

Resolves all .SUBCKT definitions and X instances inline, producing a flat
netlist that parse_netlist() can handle without needing subcircuit support.

Adapted from subckt_resolver/spice_flatten.py (vrajesh_sandbox branch).

Public API:
    flatten_netlist(text, base_dir=".") -> str

Supports (SPICE 3F5 spec):
    - .SUBCKT / .ENDS (including nested subcircuits)
    - .GLOBAL node declarations (global nets bypass hierarchy and are never renamed)
    - Line continuation ('+' in column 1)
    - .INCLUDE / .LIB file includes (when base_dir is provided)
    - All comment forms: '*' in column 1, leading whitespace (SPICE 3 rule)
    - All device types: M, Q, J, Z, D, R, C, L, V, I, G, E, F, H, K, B, S, W

Does NOT support (simulator extensions, not part of SPICE 3F5 base spec):
    - .PARAM / PARAMS: parameterized subcircuits
    - {expression} syntax
    - $ inline comments (ngspice extension)
"""

import re
import os
import sys


class SubcktDefinition:
    """Represents a parsed .SUBCKT definition."""
    def __init__(self, name: str, ports: list, lines: list):
        self.name  = name
        self.ports = ports
        self.lines = lines   # lines inside the block, excluding .SUBCKT and .ENDS

    def __repr__(self):
        return f"Subckt({self.name}, ports={self.ports}, {len(self.lines)} lines)"


class SpiceFlattener:
    """
    Parses a SPICE netlist (from file or string) and flattens all
    subcircuit instances into top-level elements.
    """

    def __init__(self):
        self.subcircuits: dict[str, SubcktDefinition] = {}
        self.top_level_lines: list[str] = []
        self.included_files: set[str] = set()
        self.base_dir: str = "."
        # Node names that are never prefixed during flattening.
        # Pre-populated with universally-standard power/ground names;
        # extended at parse time by any .GLOBAL declarations in the netlist.
        # Stored uppercase because SPICE node names are case-insensitive.
        self.global_nodes: set[str] = {"GND", "VDD", "VSS", "VDDA", "VSSA", "0"}

    # ── Public entry points ─────────────────────────────────────────────

    def parse_text(self, text: str, base_dir: str = "."):
        """Parse a SPICE netlist from a string."""
        self.base_dir = base_dir
        raw_lines = text.splitlines()
        lines = self._process_line_continuation(raw_lines)
        self._parse_lines(lines, is_top_level=True, source_file=None)

    def parse_file(self, filename: str, is_top_level: bool = True):
        """Parse a SPICE netlist from a file path."""
        abs_filename = os.path.abspath(filename)
        if abs_filename in self.included_files:
            return
        self.included_files.add(abs_filename)
        if is_top_level:
            self.base_dir = os.path.dirname(abs_filename)
        try:
            with open(abs_filename) as f:
                raw_lines = f.readlines()
        except FileNotFoundError:
            print(f"Warning: could not open {abs_filename}", file=sys.stderr)
            return
        lines = self._process_line_continuation(raw_lines)
        self._parse_lines(lines, is_top_level=is_top_level,
                          source_file=abs_filename)

    def flatten(self) -> list[str]:
        """Return flat netlist as a list of lines."""
        result = []
        for line in self.top_level_lines:
            if self._is_x_instance(line):
                result.extend(self._flatten_instance(line, prefix=""))
            else:
                result.append(line)
        return result

    def flatten_text(self) -> str:
        """Return flat netlist as a single string."""
        return "\n".join(self.flatten())

    # ── Internal parsing ────────────────────────────────────────────────

    def _process_line_continuation(self, raw_lines: list[str]) -> list[str]:
        """
        Join continuation lines ('+' in column 1 per SPICE 3F5 sec2).
        Reads from column 2 onwards on continuation lines.
        """
        processed = []
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i].rstrip()
            while (i + 1 < len(raw_lines)
                   and raw_lines[i + 1]
                   and raw_lines[i + 1][0] == "+"):
                i += 1
                cont = raw_lines[i].rstrip()
                line = line + " " + (cont[1:].strip() if len(cont) > 1 else "")
            processed.append(line)
            i += 1
        return processed

    def _parse_lines(self, lines: list[str], is_top_level: bool,
                     source_file: str | None):
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()

            # Comments: '*' in column 1 OR leading whitespace (SPICE 3 rule)
            if line and (line[0] == "*" or line[0].isspace()):
                if is_top_level:
                    self.top_level_lines.append(line)
                i += 1
                continue

            upper = line.upper().strip()

            if upper.startswith(".SUBCKT"):
                subckt, end_idx = self._parse_subcircuit(lines, i)
                self.subcircuits[subckt.name.upper()] = subckt
                i = end_idx + 1

            elif upper.startswith(".INCLUDE") or upper.startswith(".INC"):
                fname = self._parse_include(line)
                if fname and source_file:
                    self._process_include(fname, source_file)
                elif fname and self.base_dir:
                    self._process_include(fname,
                                          os.path.join(self.base_dir, "_"))
                if is_top_level:
                    self.top_level_lines.append(line)
                i += 1

            elif upper.startswith(".LIB"):
                lib_file, section = self._parse_lib(line)
                if lib_file:
                    ref = source_file or os.path.join(self.base_dir, "_")
                    self._process_lib(lib_file, section, ref)
                if is_top_level:
                    self.top_level_lines.append(line)
                i += 1

            elif upper.startswith(".GLOBAL"):
                # .GLOBAL node1 node2 ...
                # These nets are accessible everywhere without being in any
                # subcircuit's port list — they must never be prefixed.
                for gnode in line.strip().split()[1:]:
                    self.global_nodes.add(gnode.upper())
                if is_top_level:
                    self.top_level_lines.append(line)
                i += 1

            else:
                if is_top_level:
                    self.top_level_lines.append(line)
                i += 1

    def _parse_subcircuit(self, lines: list[str],
                          start_idx: int) -> tuple["SubcktDefinition", int]:
        header = lines[start_idx].strip()
        tokens = header.split()
        if len(tokens) < 2:
            raise ValueError(f"Invalid .SUBCKT line: {header}")

        subckt_name = tokens[1]
        ports = tokens[2:]

        body_lines = []
        i = start_idx + 1
        depth = 1
        while i < len(lines) and depth > 0:
            line = lines[i].rstrip()
            upper = line.upper().strip()
            if upper.startswith(".SUBCKT"):
                depth += 1
            elif upper.startswith(".ENDS"):
                depth -= 1
                if depth == 0:
                    break
            if depth > 0:
                body_lines.append(line)
            i += 1

        return SubcktDefinition(subckt_name, ports, body_lines), i

    def _parse_include(self, line: str) -> str | None:
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith(".INCLUDE"):
            rest = stripped[8:].strip()
        elif upper.startswith(".INC"):
            rest = stripped[4:].strip()
        else:
            return None
        return rest.strip("'\"\t ") or None

    def _parse_lib(self, line: str) -> tuple[str | None, str | None]:
        stripped = line.strip()
        if not stripped.upper().startswith(".LIB"):
            return None, None
        rest = stripped[4:].strip()
        filename = section = None
        if rest.startswith(("'", '"')):
            q = rest[0]
            end = rest.find(q, 1)
            if end > 0:
                filename = rest[1:end]
                after = rest[end + 1:].strip()
                if after:
                    section = after.strip("'\"")
        else:
            parts = rest.split()
            if parts:
                filename = parts[0].strip("'\"")
                if len(parts) > 1:
                    section = parts[1].strip("'\"")
        return filename, section

    def _resolve_path(self, filename: str, current_file: str) -> str:
        if os.path.isabs(filename):
            return filename
        cur_dir = os.path.dirname(current_file)
        candidate = os.path.join(cur_dir, filename)
        if os.path.exists(candidate):
            return candidate
        candidate = os.path.join(self.base_dir, filename)
        if os.path.exists(candidate):
            return candidate
        return filename

    def _process_include(self, fname: str, current_file: str):
        resolved = self._resolve_path(fname, current_file)
        self.parse_file(resolved, is_top_level=False)

    def _process_lib(self, lib_file: str, section: str | None,
                     current_file: str):
        resolved = self._resolve_path(lib_file, current_file)
        if section:
            self._parse_lib_section(resolved, section)
        else:
            self.parse_file(resolved, is_top_level=False)

    def _parse_lib_section(self, filename: str, section: str):
        abs_filename = os.path.abspath(filename)
        if abs_filename in self.included_files:
            return
        self.included_files.add(abs_filename)
        try:
            with open(abs_filename) as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"Warning: library not found: {abs_filename}", file=sys.stderr)
            return
        in_section = False
        section_upper = section.upper()
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            upper = line.upper().strip()
            if upper.startswith(".LIB") and section_upper in upper:
                in_section = True
                i += 1
                continue
            if upper.startswith(".ENDL") and in_section:
                break
            if in_section:
                if upper.startswith(".SUBCKT"):
                    cont_lines = self._process_line_continuation(lines)
                    subckt, end_idx = self._parse_subcircuit(cont_lines, i)
                    self.subcircuits[subckt.name.upper()] = subckt
                    i = end_idx + 1
                    continue
            i += 1

    # ── Flattening ──────────────────────────────────────────────────────

    def _is_x_instance(self, line: str) -> bool:
        stripped = line.strip()
        return bool(stripped) and not stripped.startswith("*") \
               and stripped[0].upper() == "X"

    def _flatten_instance(self, instance_line: str, prefix: str,
                          depth: int = 0) -> list[str]:
        tokens = instance_line.split()
        if len(tokens) < 2:
            return [instance_line]

        instance_name = tokens[0]

        # Find the subcircuit name — last token matching a known definition
        subckt_name = None
        subckt_idx  = -1
        for i in range(len(tokens) - 1, 0, -1):
            if tokens[i].upper() in self.subcircuits:
                subckt_name = tokens[i].upper()
                subckt_idx  = i
                break

        if subckt_name is None:
            return [f"{instance_line}  * WARNING: subcircuit not found"]

        connected_nodes = tokens[1:subckt_idx]
        subckt = self.subcircuits[subckt_name]

        if len(connected_nodes) != len(subckt.ports):
            return [f"{instance_line}  "
                    f"* ERROR: port count mismatch "
                    f"({len(connected_nodes)} given, "
                    f"{len(subckt.ports)} expected)"]

        port_map = dict(zip(subckt.ports, connected_nodes))
        unique_prefix = f"{prefix}_{instance_name}" if prefix else instance_name

        result = [
            f"* --- begin flattened instance: {unique_prefix} ({subckt_name})",
        ]
        for subckt_line in subckt.lines:
            if self._is_x_instance(subckt_line):
                nested = self._flatten_instance(subckt_line, unique_prefix,
                                                depth + 1)
                for nl in nested:
                    result.append(
                        self._rename_nodes_in_line(nl, port_map, unique_prefix)
                    )
            else:
                result.append(
                    self._rename_line(subckt_line, port_map, unique_prefix)
                )
        result.append(f"* --- end flattened instance: {unique_prefix}")
        return result

    def _rename_line(self, line: str, port_map: dict[str, str],
                     prefix: str) -> str:
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            return line
        if line and line[0].isspace():    # SPICE 3 whitespace-comment rule
            return line
        if stripped.startswith("+"):
            return line
        if stripped.startswith("."):
            return line

        tokens = line.split()
        if not tokens:
            return line

        device_name = tokens[0]
        dtype       = device_name[0].upper()

        if dtype != "X":
            new_name = (f"{dtype}_{prefix}_{device_name[1:]}"
                        if prefix else device_name)
        else:
            new_name = (f"{prefix}_{device_name}" if prefix else device_name)

        node_count, _ = self._device_node_count(dtype, tokens)
        new_tokens    = [new_name]
        for i in range(1, min(node_count + 1, len(tokens))):
            new_tokens.append(self._rename_node(tokens[i], port_map, prefix))
        for i in range(node_count + 1, len(tokens)):
            new_tokens.append(tokens[i])
        return " ".join(new_tokens)

    def _rename_nodes_in_line(self, line: str, port_map: dict[str, str],
                               prefix: str) -> str:
        stripped = line.strip()
        if not stripped or stripped.startswith("*") or stripped.startswith("."):
            return line
        tokens = line.split()
        if not tokens:
            return line
        dtype      = self._extract_device_type(tokens[0])
        node_count = self._device_node_count(dtype, tokens)[0] if dtype else len(tokens) - 1
        new_tokens = [tokens[0]]
        for i in range(1, min(node_count + 1, len(tokens))):
            new_tokens.append(self._rename_node(tokens[i], port_map, prefix))
        for i in range(node_count + 1, len(tokens)):
            new_tokens.append(tokens[i])
        return " ".join(new_tokens)

    def _rename_node(self, node: str, port_map: dict[str, str],
                     prefix: str) -> str:
        if node in port_map:
            return port_map[node]
        if node.upper() in self.global_nodes:   # standard + .GLOBAL declared nets
            return node
        return f"{prefix}_{node}"

    # ── Device metadata ─────────────────────────────────────────────────

    # node counts per SPICE 3F5 device letter
    _NODE_COUNT: dict[str, int] = {
        "M": 4,  # MOSFET: D G S B
        "Q": 3,  # BJT:    C B E  (optional S not counted here)
        "J": 3,  # JFET:   D G S
        "Z": 3,  # MESFET: D G S
        "D": 2,  # Diode:  N+ N-
        "R": 2,  # Resistor
        "C": 2,  # Capacitor
        "L": 2,  # Inductor
        "K": 2,  # Mutual inductor (references, not nets — kept for completeness)
        "V": 2,  # V source
        "I": 2,  # I source
        "E": 4,  # VCVS:  N+ N- NC+ NC-
        "G": 4,  # VCCS:  N+ N- NC+ NC-
        "F": 2,  # CCCS:  N+ N-  (VNAM is not a node)
        "H": 2,  # CCVS:  N+ N-  (VNAM is not a node)
        "B": 2,  # Nonlinear source: N+ N-
        "S": 4,  # Voltage switch: N+ N- NC+ NC-
        "W": 2,  # Current switch: N+ N-
        "T": 4,  # Lossless TX line: N1 N2 N3 N4
        "O": 4,  # Lossy TX line:    N1 N2 N3 N4
        "U": 3,  # Distributed RC:   N1 N2 N3
    }

    def _device_node_count(self, dtype: str,
                            tokens: list[str]) -> tuple[int, int]:
        n = self._NODE_COUNT.get(dtype.upper(), 0)
        if n:
            return n, n + 1
        # Fallback: scan for '=' to find start of parameters
        for i in range(1, len(tokens)):
            if "=" in tokens[i]:
                return i - 1, -1
        return len(tokens) - 1, -1

    def _extract_device_type(self, device_name: str) -> str | None:
        valid = set("MQJZDRCLVIEGFHKBSTWOU")
        parts = device_name.split("_")
        if parts:
            first = parts[-1]
            if first and first[0].upper() in valid:
                return first[0].upper()
        for ch in device_name:
            if ch.upper() in valid:
                return ch.upper()
        return None

    # ── File output ─────────────────────────────────────────────────────

    def write_flattened(self, output_filename: str):
        """Write the flattened netlist to a file."""
        with open(output_filename, "w") as f:
            for line in self.flatten():
                f.write(line + "\n")


# ── Module-level convenience function ──────────────────────────────────

def flatten_netlist(text: str, base_dir: str = ".") -> str:
    """
    Flatten a hierarchical SPICE netlist given as a string.

    Resolves all .SUBCKT definitions and X subcircuit instances inline.
    .INCLUDE / .LIB references are resolved relative to base_dir if provided.

    Args:
        text:     SPICE netlist as a string
        base_dir: directory used to resolve .INCLUDE / .LIB paths

    Returns:
        Flat netlist string (all X instances replaced with their contents).
    """
    f = SpiceFlattener()
    f.parse_text(text, base_dir=base_dir)
    return f.flatten_text()


# ── CLI ─────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python spice_flatten.py <input> [output]")
        sys.exit(1)

    inp = sys.argv[1]
    out = (sys.argv[2] if len(sys.argv) >= 3
           else re.sub(r"(\.\w+)?$", "_flat\\1", inp))

    print(f"Flattening: {inp}")
    f = SpiceFlattener()
    try:
        f.parse_file(inp)
        print(f"  {len(f.subcircuits)} subcircuit(s): "
              + ", ".join(f.subcircuits))
        f.write_flattened(out)
        print(f"  Written: {out}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
