def is_control_relevant(transistor, graph):
    gate = graph.gate_net(transistor)
    return not is_constant_net(gate, graph)

