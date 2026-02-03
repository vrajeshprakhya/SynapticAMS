def extract_blocks(signal_graph):
    return list(nx.connected_components(signal_graph))

