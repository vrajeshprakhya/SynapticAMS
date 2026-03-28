import networkx as nx
import re

# ----------------------------------------
# Device terminal definitions
# ----------------------------------------
DEVICE_TERMINALS = {
    "M": ["D", "G", "S", "B"],   # MOSFET
    "Q": ["C", "B", "E"],       # BJT
    "R": ["1", "2"],
    "C": ["1", "2"],
    "L": ["1", "2"],
    "V": ["+", "-"],
    "I": ["+", "-"],
}

# ----------------------------------------
# SPICE netlist parser
# ----------------------------------------
def parse_spice_netlist(netlist_text):
    devices = []
    in_control = False

    for line in netlist_text.splitlines():
        line = line.strip()

        # Track .control/.endc blocks and skip their contents
        upper = line.upper()
        if upper.startswith(".CONTROL"):
            in_control = True
            continue
        if upper.startswith(".ENDC"):
            in_control = False
            continue
        if in_control:
            continue

        # Skip comments and control lines
        if not line or line.startswith("*") or line.startswith("."):
            continue

        tokens = re.split(r"\s+", line)
        dev_name = tokens[0]
        dev_type = dev_name[0].upper()

        if dev_type not in DEVICE_TERMINALS:
            continue  # unsupported device

        terminals = DEVICE_TERMINALS[dev_type]
        net_count = len(terminals)

        if len(tokens) < net_count + 1:
            raise ValueError(f"Malformed line: {line}")

        nets = tokens[1 : 1 + net_count]

        devices.append({
            "name": dev_name,
            "type": dev_type,
            "nets": dict(zip(terminals, nets)),
            "raw": line
        })

    return devices

# ----------------------------------------
# Bipartite graph builder
# ----------------------------------------
def build_bipartite_graph(devices):
    G = nx.Graph()

    for dev in devices:
        dev_node = f"dev:{dev['name']}"
        G.add_node(
            dev_node,
            kind="device",
            device_type=dev["type"],
            raw=dev["raw"]
        )

        for terminal, net in dev["nets"].items():
            net_node = f"net:{net}"

            G.add_node(
                net_node,
                kind="net"
            )

            G.add_edge(
                net_node,
                dev_node,
                terminal=terminal,
                device_type=dev["type"]
            )

    return G

# ----------------------------------------
# Pretty printer
# ----------------------------------------
def print_graph(G):
    print("\n=== NODES ===")
    for node, data in G.nodes(data=True):
        print(f"{node}: {data}")

    print("\n=== EDGES ===")
    for u, v, data in G.edges(data=True):
        print(f"{u} -- {v} : {data}")

# ----------------------------------------
# Example: YOUR NETLIST
# ----------------------------------------
if __name__ == "__main__":
    spice_netlist = """
    *MOSFET Differential Pair Netlist
    M2 2 5 4 4 PMOS L=1u W=1u
    M1 2 5 3 3 NMOS L=1u W=1u
    VDD 4 0 DC 5V
    Vin 5 0 DC 0V
    """

    devices = parse_spice_netlist(spice_netlist)
    G = build_bipartite_graph(devices)
    print_graph(G)

