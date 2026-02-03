def analyze_blocks(graph, constant_nets, control_relevant_devices):
    signal_graph = build_signal_graph(
        graph,
        constant_nets,
        control_relevant_devices
    )

    blocks = extract_blocks(signal_graph)

    block_ios = []
    for i, block in enumerate(blocks):
        inputs, outputs = extract_block_io(block, graph)
        block_ios.append({
            "block_id": i,
            "nodes": block,
            "inputs": inputs,
            "outputs": outputs,
        })

    return block_ios

