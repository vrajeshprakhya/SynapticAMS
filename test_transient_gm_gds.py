#!/usr/bin/env python3
"""
Test transient-based gm/gds extraction against standard .OP method.

Compares two extraction methods:
1. Standard: .OP analysis + show command (built-in ngspice)
2. Transient: AC perturbation + FFT analysis (custom implementation)

This validates that the transient method produces results consistent
with the established .OP approach.
"""

from ngspice_runner import NgspiceRunner

def test_nmos_extraction():
    """
    Test gm/gds extraction for a simple NMOS device at multiple bias points.
    """
    print("="*70)
    print("  NMOS gm/gds Extraction: Transient vs .OP Method")
    print("="*70)

    # NMOS device model
    netlist = """
* Simple NMOS test circuit
M1 vd vg 0 0 NMOS W=10u L=1u
VDD vd 0 DC 1.8
Vin vg 0 DC 0.9
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

    runner = NgspiceRunner()

    # Test at multiple bias points
    bias_points = [
        {'vg': 0.5, 'vd': 1.8, 'region': 'subthreshold'},
        {'vg': 0.7, 'vd': 1.8, 'region': 'weak inversion'},
        {'vg': 0.9, 'vd': 1.8, 'region': 'moderate inversion'},
        {'vg': 1.2, 'vd': 1.8, 'region': 'strong inversion'},
        {'vg': 0.9, 'vd': 0.5, 'region': 'linear region (low Vds)'},
    ]

    print("\n{:>4} {:>8} {:>8}  {:>12} {:>12}  {:>12} {:>12}  {:>8}  {}".format(
        "#", "Vgs(V)", "Vds(V)", "gm_OP(S)", "gm_tran(S)",
        "gds_OP(S)", "gds_tran(S)", "gm_err%", "Region"))
    print("-"*110)

    for i, bias in enumerate(bias_points, 1):
        vg = bias['vg']
        vd = bias['vd']
        region = bias['region']

        # ── Method 1: Standard .OP + show ──────────────────────────────
        netlist_biased = netlist.replace('DC 0.9', f'DC {vg}')
        netlist_biased = netlist_biased.replace('DC 1.8', f'DC {vd}', 1)

        try:
            params_op = runner.extract_ac_params(netlist_biased, ['M1'])
            gm_op = params_op['M1']['gm']
            gds_op = params_op['M1']['gds']
        except Exception as e:
            print(f"{i:>4} {vg:>8.2f} {vd:>8.2f}  {'FAILED':>12}  (OP method failed: {e})")
            continue

        # ── Method 2: Transient with AC perturbation ───────────────────
        try:
            params_tran = runner.extract_ac_params_transient(
                netlist,
                'M1',
                vg_dc=vg,
                vd_dc=vd,
                perturbation_mv=10.0,  # 10 mV perturbation
                freq_hz=1e6,            # 1 MHz test frequency
                n_periods=5
            )
            gm_tran = params_tran['gm']
            gds_tran = params_tran['gds']
        except Exception as e:
            print(f"{i:>4} {vg:>8.2f} {vd:>8.2f}  {gm_op:>12.3e}  {'FAILED':>12}  (Transient failed: {e})")
            continue

        # ── Compare results ────────────────────────────────────────────
        gm_error = abs(gm_tran - gm_op) / (gm_op + 1e-15) * 100 if gm_op != 0 else float('inf')
        gds_error = abs(gds_tran - gds_op) / (gds_op + 1e-15) * 100 if gds_op != 0 else float('inf')

        print(f"{i:>4} {vg:>8.2f} {vd:>8.2f}  "
              f"{gm_op:>12.3e} {gm_tran:>12.3e}  "
              f"{gds_op:>12.3e} {gds_tran:>12.3e}  "
              f"{gm_error:>7.1f}%  {region}")

    print("\n" + "="*70)


def test_pmos_extraction():
    """
    Test gm/gds extraction for PMOS device.
    """
    print("\n" + "="*70)
    print("  PMOS gm/gds Extraction: Transient vs .OP Method")
    print("="*70)

    netlist = """
* Simple PMOS test circuit
M1 vd vg vdd vdd PMOS W=10u L=1u
VDD vdd 0 DC 1.8
VD vd 0 DC 0.2
Vin vg 0 DC 0.9
.model PMOS PMOS (LEVEL=1 VTO=-0.4 KP=50u LAMBDA=0.02)
"""

    runner = NgspiceRunner()

    # PMOS: Vgs = Vg - Vdd (typically negative), Vds = Vd - Vdd (negative)
    # For |Vgs| = 0.9V: Vg = 1.8 - 0.9 = 0.9V
    # For |Vds| = 1.6V: Vd = 1.8 - 1.6 = 0.2V

    bias_points = [
        {'vg': 0.9, 'vd': 0.2, 'region': 'saturation (|Vgs|=0.9V, |Vds|=1.6V)'},
    ]

    print("\n{:>4} {:>8} {:>8}  {:>12} {:>12}  {:>12} {:>12}  {}".format(
        "#", "Vg(V)", "Vd(V)", "gm_OP(S)", "gm_tran(S)",
        "gds_OP(S)", "gds_tran(S)", "Region"))
    print("-"*100)

    for i, bias in enumerate(bias_points, 1):
        vg = bias['vg']
        vd = bias['vd']
        region = bias['region']

        netlist_biased = netlist.replace('DC 0.9', f'DC {vg}')
        netlist_biased = netlist_biased.replace('DC 0.2', f'DC {vd}')

        # Standard method
        try:
            params_op = runner.extract_ac_params(netlist_biased, ['M1'])
            gm_op = params_op['M1']['gm']
            gds_op = params_op['M1']['gds']
        except Exception as e:
            print(f"{i:>4} {vg:>8.2f} {vd:>8.2f}  FAILED (OP: {e})")
            continue

        # Transient method
        try:
            params_tran = runner.extract_ac_params_transient(
                netlist,
                'M1',
                vg_dc=vg,
                vd_dc=vd,
                perturbation_mv=10.0,
                freq_hz=1e6,
                n_periods=5
            )
            gm_tran = params_tran['gm']
            gds_tran = params_tran['gds']
        except Exception as e:
            print(f"{i:>4} {vg:>8.2f} {vd:>8.2f}  {gm_op:>12.3e}  FAILED (Transient: {e})")
            continue

        print(f"{i:>4} {vg:>8.2f} {vd:>8.2f}  "
              f"{gm_op:>12.3e} {gm_tran:>12.3e}  "
              f"{gds_op:>12.3e} {gds_tran:>12.3e}  {region}")

    print("\n" + "="*70)


def test_frequency_dependence():
    """
    Test how gm/gds extraction varies with perturbation frequency.

    At low frequencies, the extraction should match DC values.
    At high frequencies, parasitic capacitances may affect results.
    """
    print("\n" + "="*70)
    print("  Frequency Dependence of Transient Extraction")
    print("="*70)

    netlist = """
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

    runner = NgspiceRunner()
    vg_dc = 0.9
    vd_dc = 1.8

    # Test at different frequencies
    frequencies = [1e3, 10e3, 100e3, 1e6, 10e6, 100e6]  # 1kHz to 100MHz

    print("\n{:>12}  {:>12} {:>12}  {:>12}".format(
        "Freq (Hz)", "gm (S)", "gds (S)", "gm/gds"))
    print("-"*60)

    for freq in frequencies:
        try:
            params = runner.extract_ac_params_transient(
                netlist,
                'M1',
                vg_dc=vg_dc,
                vd_dc=vd_dc,
                perturbation_mv=10.0,
                freq_hz=freq,
                n_periods=5
            )
            gm = params['gm']
            gds = params['gds']
            ratio = gm / gds if gds > 0 else float('inf')

            print(f"{freq:>12.3e}  {gm:>12.3e} {gds:>12.3e}  {ratio:>12.1f}")
        except Exception as e:
            print(f"{freq:>12.3e}  FAILED: {e}")

    print("\n" + "="*70)


if __name__ == '__main__':
    test_nmos_extraction()
    test_pmos_extraction()
    test_frequency_dependence()

    print("\n" + "="*70)
    print("  Test Summary")
    print("="*70)
    print("The transient-based extraction method has been implemented.")
    print("Compare the results above to validate accuracy.")
    print()
    print("Expected behavior:")
    print("  • gm and gds should match .OP method within ~10% for low frequencies")
    print("  • Larger errors may occur in edge cases (subthreshold, high frequency)")
    print("  • The transient method is more flexible but slower than .OP")
    print("="*70)
