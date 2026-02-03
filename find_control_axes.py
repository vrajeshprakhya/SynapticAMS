def find_control_axes(block):
    axes = set()
    for dev in block["control_devices"]:
        if dev["type"] == "MOS":
            axes.add(dev["terminals"]["gate"])
        elif dev["type"] == "BJT":
            axes.add(dev["terminals"]["base"])
    return axes

