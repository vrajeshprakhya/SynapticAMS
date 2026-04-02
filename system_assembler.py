"""
system_assembler.py — Top-level Verilog-AMS system assembly.

Takes N independently generated .va blocks and wires them into a system_top.va
using heuristic port name matching.  Unresolved connections are emitted as
// TODO: connect <port>  stubs so an engineer can review them in Cadence/Virtuoso.

Algorithm:
  1. Parse each .va file — extract module name and port list (direction + name).
  2. Build connectivity graph — match output ports of block A to input ports of
     block B using name-similarity rules (out↔in, vout↔vin, _p/_n pairs, etc.).
  3. Emit system_top.va with internal electrical wires for matched ports and
     module instantiations for each block.
  4. Emit instantiation_list.txt — human-readable connectivity table.

Usage:
    from system_assembler import assemble_system
    system_va = assemble_system(va_files, output_dir,
                                system_name="system_top",
                                client_id=None)
"""

import re
from pathlib import Path
from datetime import datetime


# ── Public API ─────────────────────────────────────────────────────────

def assemble_system(va_files: list,
                    output_dir: str,
                    system_name: str = "system_top",
                    client_id: str | None = None) -> Path:
    """
    Parse .va blocks and emit a system_top.va with heuristic port wiring.

    Args:
        va_files:    List of Path objects (or strings) pointing to .va files.
        output_dir:  Directory in which to write system_top.va and
                     instantiation_list.txt.
        system_name: Verilog-AMS module name for the top-level wrapper.
        client_id:   Optional — unused today, reserved for future RAG-aware wiring.

    Returns:
        Path to the written system_top.va.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Parse every block ───────────────────────────────────────
    blocks: list[dict] = []
    for va_path in va_files:
        va_path = Path(va_path)
        if not va_path.exists():
            continue
        text = va_path.read_text(errors="replace")
        mod = _parse_module(text, va_path)
        if mod:
            blocks.append(mod)

    if not blocks:
        raise ValueError("No parseable .va modules found in va_files list.")

    # ── 2. Build connectivity graph ────────────────────────────────
    wires, connections, unconnected = _wire_blocks(blocks)

    # ── 3. Emit system_top.va ──────────────────────────────────────
    va_code = _emit_system_va(system_name, blocks, wires, connections,
                               unconnected)
    system_va_path = out_dir / f"{system_name}.va"
    system_va_path.write_text(va_code)

    # ── 4. Emit instantiation_list.txt ─────────────────────────────
    table = _emit_table(blocks, wires, connections, unconnected)
    table_path = out_dir / "instantiation_list.txt"
    table_path.write_text(table)

    print(f"      System assembly: {len(blocks)} blocks, "
          f"{len(wires)} wires, {len(unconnected)} unresolved stubs")

    return system_va_path


# ── Internal: parsing ──────────────────────────────────────────────────

def _parse_module(text: str, path: Path) -> dict | None:
    """Extract module name and ports from Verilog-AMS source."""
    # Module declaration: module NAME (port, port, ...);
    m = re.search(r'\bmodule\s+(\w+)\s*\(([^)]*)\)', text)
    if not m:
        return None
    module_name = m.group(1)
    port_names_raw = [p.strip() for p in m.group(2).split(',') if p.strip()]

    # Port directions: collect all "output electrical name;" / "input electrical name;"
    # Support multi-port: "output electrical out_p, out_n;"
    port_dir: dict[str, str] = {}  # name → 'input' | 'output'
    for direction in ('output', 'input'):
        for pm in re.finditer(
            r'\b' + direction + r'\b[^;]*?(\w+(?:\s*,\s*\w+)*)\s*;',
            text,
        ):
            for name in re.split(r'\s*,\s*', pm.group(1)):
                name = name.strip()
                if name and name in port_names_raw:
                    port_dir[name] = direction

    # Fill in any undirected ports as 'inout'
    ports = []
    for name in port_names_raw:
        ports.append({
            'name': name,
            'direction': port_dir.get(name, 'inout'),
        })

    return {
        'module_name': module_name,
        'ports': ports,
        'path': path,
        'inst_name': f"i_{module_name.lower()}",
    }


# ── Internal: connectivity ─────────────────────────────────────────────

_SUFFIX_PAIRS = [
    ('_out', '_in'), ('_p', '_p'), ('_n', '_n'),
    ('out', 'in'), ('vout', 'vin'), ('output', 'input'),
]


def _name_score(out_name: str, in_name: str) -> int:
    """
    Score how well an output port name matches an input port name.
    Higher = better match.
    """
    a, b = out_name.lower(), in_name.lower()
    if a == b:
        return 10           # exact match (same net name from circuit analyzer)

    # Strip common direction suffixes and compare stems
    for osuf, isuf in _SUFFIX_PAIRS:
        if a.endswith(osuf) and b.endswith(isuf):
            stem_a = a[: -len(osuf)] if osuf else a
            stem_b = b[: -len(isuf)] if isuf else b
            if stem_a and stem_b and stem_a == stem_b:
                return 8

    # Substring match: one name contained in the other
    if a in b or b in a:
        return 3

    return 0


def _wire_blocks(blocks: list[dict]):
    """
    Match output ports of each block to input ports of other blocks.

    Returns:
        wires:        {wire_name: {'driver': (block_idx, port_name),
                                   'receivers': [(block_idx, port_name)]}}
        connections:  {(block_idx, port_name): wire_name}
        unconnected:  [(block_idx, port_name)]  — ports with no match
    """
    # Collect all output and input ports with their block index
    outputs: list[tuple[int, str]] = []
    inputs:  list[tuple[int, str]] = []
    for bi, blk in enumerate(blocks):
        for p in blk['ports']:
            if p['direction'] == 'output':
                outputs.append((bi, p['name']))
            elif p['direction'] == 'input':
                inputs.append((bi, p['name']))

    connections: dict[tuple[int, str], str] = {}
    wires: dict[str, dict] = {}
    used_inputs: set[tuple[int, str]] = set()

    for (oi, oname) in outputs:
        best_score = 0
        best_match: tuple[int, str] | None = None

        for (ii, iname) in inputs:
            if ii == oi:
                continue  # skip self-connections
            if (ii, iname) in used_inputs:
                continue
            s = _name_score(oname, iname)
            if s > best_score:
                best_score = s
                best_match = (ii, iname)

        if best_match and best_score >= 3:
            ii, iname = best_match
            wire_name = f"w_{oname.lower()}"
            wires[wire_name] = {
                'driver': (oi, oname),
                'receivers': [(ii, iname)],
            }
            connections[(oi, oname)] = wire_name
            connections[(ii, iname)] = wire_name
            used_inputs.add((ii, iname))

    # Any port not in connections is unconnected
    unconnected: list[tuple[int, str]] = []
    for bi, blk in enumerate(blocks):
        for p in blk['ports']:
            key = (bi, p['name'])
            if key not in connections:
                unconnected.append(key)

    return wires, connections, unconnected


# ── Internal: code generation ──────────────────────────────────────────

def _emit_system_va(system_name, blocks, wires, connections, unconnected) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "// Auto-generated by SynapticAMS system_assembler",
        f"// Date: {now}",
        f"// Blocks: {', '.join(b['module_name'] for b in blocks)}",
        "//",
        "// Review all  // TODO: connect  stubs before tapeout.",
        "",
        '`include "disciplines.vams"',
        "",
        f"module {system_name} ();",
        "",
        "    // ── Internal wires (auto-connected) ──────────────────",
    ]

    for wire_name in wires:
        lines.append(f"    electrical {wire_name};")

    if unconnected:
        lines.append("")
        lines.append("    // ── Unresolved stubs (review required) ─────────────")
        for (bi, pname) in unconnected:
            blk = blocks[bi]
            lines.append(f"    // TODO: connect {blk['module_name']}.{pname}")
            lines.append(f"    electrical stub_{blk['module_name'].lower()}_{pname.lower()};")

    lines.append("")
    lines.append("    // ── Block instantiations ──────────────────────────────")

    for bi, blk in enumerate(blocks):
        port_connects = []
        for p in blk['ports']:
            key = (bi, p['name'])
            if key in connections:
                wire = connections[key]
            else:
                wire = f"stub_{blk['module_name'].lower()}_{p['name'].lower()}"
            port_connects.append(f".{p['name']}({wire})")

        inst_ports = ", ".join(port_connects)
        lines.append(f"    {blk['module_name']} {blk['inst_name']} ({inst_ports});")

    lines += ["", "endmodule", ""]
    return "\n".join(lines)


def _emit_table(blocks, wires, connections, unconnected) -> str:
    lines = [
        "SynapticAMS — Instantiation / Connectivity List",
        "=" * 60,
        "",
        "BLOCKS",
        "-" * 40,
    ]
    for bi, blk in enumerate(blocks):
        lines.append(f"  [{bi}] {blk['module_name']}  ({blk['path'].name})")
        for p in blk['ports']:
            key = (bi, p['name'])
            wire = connections.get(key, "-- UNCONNECTED --")
            lines.append(f"        {p['direction']:6s}  {p['name']:20s}  → {wire}")
    lines += [
        "",
        "WIRES",
        "-" * 40,
    ]
    for wname, winfo in wires.items():
        di, dp = winfo['driver']
        driver_str = f"{blocks[di]['module_name']}.{dp}"
        receivers = ", ".join(
            f"{blocks[ri]['module_name']}.{rp}"
            for ri, rp in winfo['receivers']
        )
        lines.append(f"  {wname:30s}  {driver_str}  →  {receivers}")

    if unconnected:
        lines += [
            "",
            "UNRESOLVED (require manual connection)",
            "-" * 40,
        ]
        for bi, pname in unconnected:
            lines.append(f"  {blocks[bi]['module_name']}.{pname}")

    return "\n".join(lines) + "\n"
