"""
client_runner.py — Client-aware entry point for SynapticAMS.

Wraps run_pipeline() (AI path) and spice_to_verilog_ams() (non-AI complete
pipeline) with per-client isolation:
  • Output isolated to outputs/{client_id}/{timestamp}/
  • Per-client RAG context injected automatically
  • Returns a structured result dict

CLI:
    python client_runner.py --client apple --netlist examples/nmos_dc_sweep.cir
    python client_runner.py --client nvidia --netlist serdes.cir --complete
    python client_runner.py --netlist bjt_amplifier.cir          # no client

Python API:
    from client_runner import run_for_client
    result = run_for_client("apple", "examples/nmos_dc_sweep.cir")
    print(result["va_files"], result["nrmse"])
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path


def run_for_client(
    netlist_path: str,
    client_id: str | None = None,
    output_dir: str | None = None,
    use_complete_pipeline: bool = False,
    provider: str | None = None,
    ai_model: str | None = None,
) -> dict:
    """
    Run the SynapticAMS pipeline for a specific client.

    Args:
        netlist_path:           Path to the SPICE netlist file.
        client_id:              Client identifier (matches clients/{client_id}/).
                                Pass None to run without client context.
        output_dir:             Override output directory.  Defaults to
                                outputs/{client_id}/{timestamp}/ (or
                                outputs/generic/{timestamp}/ when no client).
        use_complete_pipeline:  If True, use the non-AI graph+fitting pipeline
                                (pipeline_ext/complete_pipeline.py).
                                If False (default), use the AI pipeline
                                (pipeline.py).
        provider:               AI backend override: 'anthropic' | 'ollama'.
        ai_model:               Model override (e.g. 'claude-opus-4-5').

    Returns:
        dict with keys:
          va_files    — list of Path objects for generated .va files
          system_va   — Path to system_top.va (or None if single block)
          testbench_dir — Path to testbenches/ directory (or None)
          nrmse       — final NRMSE float (AI pipeline only; None otherwise)
          output_dir  — Path to the output directory used
    """
    netlist_path = Path(netlist_path)
    if not netlist_path.exists():
        raise FileNotFoundError(f"Netlist not found: {netlist_path}")

    netlist_text = netlist_path.read_text()

    # ── Resolve output directory ───────────────────────────────────
    if output_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = client_id or "generic"
        output_dir = str(Path("outputs") / slug / ts)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    result: dict = {
        "va_files":      [],
        "system_va":     None,
        "testbench_dir": None,
        "nrmse":         None,
        "output_dir":    out_path,
    }

    if use_complete_pipeline:
        # ── Non-AI graph + numeric fitting pipeline ────────────────
        from pipeline_ext.complete_pipeline import spice_to_verilog_ams
        saved = spice_to_verilog_ams(netlist_text,
                                     output_dir=str(out_path),
                                     client_id=client_id)
        result["va_files"] = [f for f in saved if str(f).endswith('.va')
                              and 'system_top' not in str(f)]

        system_va = out_path / "system_top.va"
        if system_va.exists():
            result["system_va"] = system_va

        tb_dir = out_path / "testbenches"
        if tb_dir.exists():
            result["testbench_dir"] = tb_dir

    else:
        # ── AI-augmented pipeline ──────────────────────────────────
        from pipeline import run_pipeline
        va_path, nrmse = run_pipeline(
            netlist_text,
            output_dir=str(out_path),
            provider=provider,
            ai_model=ai_model,
            client_id=client_id,
        )
        result["va_files"] = [va_path]
        result["nrmse"]    = nrmse

        tb_dir = out_path / "testbenches"
        if tb_dir.exists():
            result["testbench_dir"] = tb_dir

    return result


# ── CLI ────────────────────────────────────────────────────────────────

def _main():
    parser = argparse.ArgumentParser(
        description="SynapticAMS client-aware runner: SPICE → Verilog-AMS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # AI pipeline for Apple client
  python client_runner.py --client apple --netlist examples/nmos_dc_sweep.cir

  # Non-AI complete pipeline (graph + numeric fitting)
  python client_runner.py --client nvidia --netlist serdes.cir --complete

  # No client (generic run)
  python client_runner.py --netlist examples/bjt_amplifier.cir

  # Force Claude backend
  python client_runner.py --client apple --netlist serdes.cir --provider anthropic
        """,
    )
    parser.add_argument("--netlist",  required=True, help="Path to SPICE netlist (.cir/.sp)")
    parser.add_argument("--client",   default=None,  help="Client ID (matches clients/<id>/ directory)")
    parser.add_argument("--output",   default=None,  help="Override output directory")
    parser.add_argument("--complete", action="store_true",
                        help="Use non-AI complete pipeline (graph + numeric fitting)")
    parser.add_argument("--provider", default=None,  help="AI backend: anthropic | ollama")
    parser.add_argument("--model",    default=None,  help="AI model override")
    args = parser.parse_args()

    print(f"\nSynapticAMS Client Runner")
    print(f"  Netlist : {args.netlist}")
    print(f"  Client  : {args.client or '(none)'}")
    print(f"  Pipeline: {'complete (non-AI)' if args.complete else 'AI-augmented'}")
    print()

    try:
        result = run_for_client(
            netlist_path=args.netlist,
            client_id=args.client,
            output_dir=args.output,
            use_complete_pipeline=args.complete,
            provider=args.provider,
            ai_model=args.model,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nResults:")
    print(f"  Output dir  : {result['output_dir']}")
    print(f"  VA files    : {[str(f) for f in result['va_files']]}")
    if result["system_va"]:
        print(f"  System top  : {result['system_va']}")
    if result["testbench_dir"]:
        print(f"  Testbenches : {result['testbench_dir']}")
    if result["nrmse"] is not None:
        print(f"  NRMSE       : {result['nrmse']:.4f}")


if __name__ == "__main__":
    _main()
