def extract_block_io(block_nodes, graph):
    inputs = set()
    outputs = set()

    block_nodes = set(block_nodes)

    for node in block_nodes:
        if graph.node_kind(node) != "net":
            continue

        net = node
        connected = graph.net_to_devices[net]

        for dev, pin in connected:
            dtype = graph.device_type.get(dev)

            if dev not in block_nodes:
                # connection to outside world
                if pin in CONTROL_PINS.get(dtype, set()):
                    inputs.add(net)
                if pin in OUTPUT_PINS.get(dtype, set()):
                    outputs.add(net)

    return inputs, outputs

