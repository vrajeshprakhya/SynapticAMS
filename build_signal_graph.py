import networkx as nx

def build_signal_graph(graph, constant_nets, control_relevant_devices):
    G = nx.Graph()

    # add remaining nets
    for net in graph.nets:
        if net not in constant_nets:
            G.add_node(net, kind="net")

    # add only control-relevant devices
    for dev in control_relevant_devices:
        G.add_node(dev, kind="device")

        for pin, net in graph.device_to_nets[dev].items():
            if net not in constant_nets:
                G.add_edge(dev, net)

    return G

