def is_constant_net(net, graph):
    visited = set()
    stack = [net]

    while stack:
        n = stack.pop()
        if n in visited:
            continue
        visited.add(n)

        for dev, pin in graph.net_to_devices[n]:
            dtype = graph.device_type[dev]

            if dtype == "V":
                continue  # ideal voltage source → termination

            if dtype in PASSIVE_DEVICES:
                # passive → walk through
                for other_net in graph.device_nets(dev):
                    if other_net != n:
                        stack.append(other_net)
                continue

            if pin in ACTIVE_OUTPUT_PINS.get(dtype, set()):
                return False  # reached active output

            # active but control terminal → keep walking
            for other_net in graph.device_nets(dev):
                if other_net != n:
                    stack.append(other_net)

    return True

# All paths from gate terminate in:
#  - Ideal voltage sources
#  - Or ground
# And:
#  - No path reaches an active device terminal capable of output 
#
#  ACTIVE_OUTPUT_PINS = {
#    "MOSFET": {"D", "S"},
#    "BJT": {"C", "E"},
#    "VCVS": {"OUT"},
#    "VCCS": {"OUT"},
#}

#PASSIVE_DEVICES = {"R", "C", "L"}
