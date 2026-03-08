def extract_small_signal_model(dc_op):
    """
    Extract first-order small-signal model from DC operating point

    Inputs:
        dc_op: dict with gm, gds, (optional gmb)

    Returns:
        Small-signal behavioral model
    """

    gm = dc_op.get("gm", 0.0)
    gds = dc_op.get("gds", 0.0)
    gmb = dc_op.get("gmb", 0.0)

    model = {
        "type": "small_signal",
        "validity": "linearized about DC operating point",
        "equations": [],
        "parameters": {
            "gm": gm,
            "gds": gds,
            "gmb": gmb
        }
    }

    # Drain current small-signal equation
    eq = "id = gm*vgs + gds*vds"
    if gmb != 0.0:
        eq += " + gmb*vbs"

    model["equations"].append(eq)

    return model

"""

{
  'type': 'small_signal',
  'validity': 'linearized about DC operating point',
  'equations': [
    'id = gm*vgs + gds*vds'
  ],
  'parameters': {
    'gm': 6.216e-05,
    'gds': 3.6e-07,
    'gmb': 0.0
  }
}

"""
