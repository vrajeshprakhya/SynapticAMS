def extract_small_signal_model(dc_op):
    """
    Extract first-order small-signal model from DC operating point data.

    Args:
        dc_op: dict with 'gm', 'gds', and optionally 'gmb'

    Returns:
        dict describing the small-signal model
    """
    gm  = dc_op.get("gm",  0.0)
    gds = dc_op.get("gds", 0.0)
    gmb = dc_op.get("gmb", 0.0)

    eq = "id = gm*vgs + gds*vds"
    if gmb:
        eq += " + gmb*vbs"

    return {
        "type":     "small_signal",
        "validity": "linearized about DC operating point",
        "equations": [eq],
        "parameters": {"gm": gm, "gds": gds, "gmb": gmb},
    }
