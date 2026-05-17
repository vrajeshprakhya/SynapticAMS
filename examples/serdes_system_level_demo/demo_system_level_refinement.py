#!/usr/bin/env python3
"""
System-Level Model Extraction + AI Refinement Demo
===================================================
Extract ONE behavioral model for the complete system (not internal blocks)
Then refine it with the 3-pass AI validation loop.

Usage:
    python3 demo_system_level_refinement.py <netlist.cir> [--output-dir <path>]
"""

import sys
import argparse
from pathlib import Path

# Resolve repo root from this file's location:
#   examples/serdes_system_level_demo/demo_system_level_refinement.py
#                ↑ _HERE             ↑ _REPO (two levels up)
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_HERE))   # for extract_system_model (same directory)
sys.path.insert(0, str(_REPO))   # for ngspice_runner, demo_warmstart_validated, pipeline_ext

# Import custom system-level extractor
from extract_system_model import extract_system_level_model

# Import AI refinement from main demo
from demo_warmstart_validated import (
    Colors, print_banner, print_step, print_info, print_success,
    print_warning, print_error, extract_module_ports, validate_module,
    fix_openvaf_compatibility
)


def main():
    print_banner("System-Level Model Extraction + AI Refinement")
    print_info("Extract ONE model for complete system, then refine with AI")

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Extract and refine system-level behavioral model"
    )
    parser.add_argument("netlist", type=str, help="Path to SPICE netlist (.cir file)")
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: /tmp/system_model_<netlist_name>)"
    )

    args = parser.parse_args()

    netlist_path = Path(args.netlist)
    if not netlist_path.exists():
        print_error(f"Netlist not found: {netlist_path}")
        sys.exit(1)

    # Create output directory
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    else:
        output_dir = Path("/tmp") / f"system_model_{netlist_path.stem}"
        output_dir = output_dir.resolve()

    output_dir.mkdir(parents=True, exist_ok=True)

    print_info(f"Input: {netlist_path}")
    print_info(f"Output: {output_dir}\n")

    # Step 1: Extract system-level baseline model
    print_step(1, 3, "Extracting system-level baseline model...")
    baseline_dir = output_dir / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    try:
        va_file = extract_system_level_model(str(netlist_path), str(baseline_dir))
        baseline_va = Path(va_file).read_text()
        module_name = Path(va_file).stem

        print_success(f"Baseline model: {va_file}")

    except Exception as e:
        print_error(f"Baseline extraction failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 2: AI Refinement with 3-pass validation loop
    print_step(2, 3, "Running AI refinement with validation...")

    import os
    from ai_agent import create_agent

    agent = None
    try:
        agent = create_agent()
        print_info(f"Using AI backend: {type(agent).__name__}/{agent.model}")
    except RuntimeError as e:
        print_warning(f"No AI backend available — skipping AI refinement, using baseline model\n  ({e})")

    # Read netlist
    netlist_text = netlist_path.read_text()

    # Build block_info for validation
    inputs, outputs = extract_module_ports(baseline_va)
    block_info = {
        'name': module_name,
        'inputs': set(f'net:{inp}' for inp in inputs),
        'outputs': set(f'net:{out}' for out in outputs),
        'simulation_axes': set(f'net:{inp}' for inp in inputs),
        'behavior_class': 'NONLINEAR'
    }

    print_info(f"Module: {module_name}")
    print_info(f"Inputs: {', '.join(inputs)}")
    print_info(f"Outputs: {', '.join(outputs)}")

    # Default: use baseline if AI is unavailable or fails
    final_va     = baseline_va
    final_source = "baseline"
    pass1_va     = None

    if agent is None:
        # No AI backend available — skip refinement passes entirely
        pass
    else:
        system_prompt = """You are a Verilog-AMS expert specializing in circuit behavioral modeling.
Your task is to refine numerically-fitted Verilog-AMS models to improve accuracy.
The code will be compiled with OpenVAF (a strict subset of Verilog-AMS).

=== OpenVAF HARD CONSTRAINTS — violating these causes compile failure ===
❌ NO arrays of any kind: no `real x[N]`, no `real x[N][M]`
❌ NO `M_PI` macro — use 3.141592653589793 directly
❌ NO laplace_nd(), laplace_zd(), zi_nd(), or any filter functions
❌ NO $random, white_noise(), flicker_noise()
❌ NO variable declarations inside `analog begin` blocks

=== ALLOWED — use these instead ===
✅ Simple algebraic expressions: +, -, *, /, pow(), exp(), tanh(), abs()
✅ ddt(), idt() for dynamics
✅ if/else for piecewise models
✅ `parameter real` at module scope (NOT inside analog begin)
✅ `real` variables at module scope (NOT inside analog begin)

CRITICAL: Output ONLY valid Verilog-AMS code. No markdown, no explanations."""

        user_prompt = f"""Refine this baseline Verilog-AMS model to improve accuracy.

SPICE Netlist (Complete Integrated SerDes RX):
```
{netlist_text}
```

Baseline Verilog-AMS Model (system-level):
```
{baseline_va}
```

This model represents the COMPLETE SerDes RX system:
- Inputs: tx_p_src, tx_n_src (differential input from transmitter)
- Output: final_out (recovered signal)
- System includes: Channel → CTLE → VGA → Summer

Instructions:
1. The output is driven by the DIFFERENTIAL input: V_diff = V(tx_p_src) - V(tx_n_src)
2. Model the nonlinear transfer function using tanh() saturation:
   V_out = voh * tanh(gain * (V_diff - vth)) + vbias
3. Use ONLY `parameter real` and `real` at module scope — NO arrays
4. Keep the module port list identical to the baseline
5. Declare all `real` variables at module scope (before `analog begin`)

Output the refined module code ONLY. No explanations."""

        # PASS 1: Initial AI refinement
        print(f"\n{Colors.CYAN}Pass 1:{Colors.END} AI refinement...", end="", flush=True)

        try:
            pass1_va = agent.chat(system_prompt, user_prompt)

            # Clean up AI output
            if "```" in pass1_va:
                code_lines = []
                in_fence = False
                for line in pass1_va.split('\n'):
                    if line.strip().startswith('```'):
                        in_fence = not in_fence
                        continue
                    if in_fence or (not in_fence and 'module ' in line):
                        code_lines.append(line)
                pass1_va = '\n'.join(code_lines)

            if "module " in pass1_va:
                module_start = pass1_va.find("module ")
                if module_start > 0:
                    pass1_va = pass1_va[module_start:]

            if "endmodule" in pass1_va:
                pass1_va = pass1_va[:pass1_va.rfind("endmodule") + len("endmodule")]

            if "`include" not in pass1_va and "module " in pass1_va:
                pass1_va = "`include \"disciplines.vams\"\n\n" + pass1_va

            pass1_va = fix_openvaf_compatibility(pass1_va)

            size_change = len(pass1_va) - len(baseline_va)
            print(f" {Colors.GREEN}✓{Colors.END} ({size_change:+d} chars)")

            pass1_dir = output_dir / "pass1"
            pass1_dir.mkdir(parents=True, exist_ok=True)
            (pass1_dir / f"{module_name}.va").write_text(pass1_va)

        except Exception as e:
            print(f" {Colors.RED}✗{Colors.END} Failed: {e}")
            print_warning("Pass 1 failed — using baseline as final result")
            pass1_va = None

        # PASS 2: Validation (only if Pass 1 produced a result)
        if pass1_va is not None:
            print(f"{Colors.CYAN}Pass 2:{Colors.END} Equivalence check...", end="", flush=True)

            passed, metrics, error_msg = validate_module(
                module_name, pass1_va, netlist_text, block_info, output_dir
            )

            if passed:
                print(f" {Colors.GREEN}✓ PASS{Colors.END} (err={metrics['max_abs_error']:.2e}, corr={metrics['correlation']:.3f})")
                final_va     = pass1_va
                final_source = "pass1_refined"

            else:
                if error_msg:
                    print(f" {Colors.YELLOW}⚠ FAIL{Colors.END} - {error_msg[:80]}...")
                else:
                    print(f" {Colors.YELLOW}⚠ FAIL{Colors.END} (err={metrics.get('max_abs_error', 'N/A')})")

                # PASS 3: Error correction
                print(f"{Colors.CYAN}Pass 3:{Colors.END} AI error correction...", end="", flush=True)

                correction_prompt = f"""Your previous Verilog-AMS model FAILED OpenVAF compilation. Fix it.

=== COMPILATION FAILURE ===
{error_msg if error_msg else f"Poor accuracy: max_error={metrics.get('max_abs_error', 'N/A')}, correlation={metrics.get('correlation', 'N/A')}"}

=== YOUR FAILED CODE ===
```
{pass1_va}
```

=== COMMON FIX: If you used arrays, remove them ===
OpenVAF does NOT support arrays. If your code has `real name[N]` or `real name[N][M]`,
replace with an algebraic expression like:
  V(out) <+ vbias + vamp * tanh(gain * (V(inp) - V(inn) - vth));

=== WRITE A SIMPLE ALGEBRAIC MODEL ===
Use this structure (guaranteed to compile):
  `include "disciplines.vams"
  module serdes_rx_system(final_out, tx_p_src, tx_n_src);
    inout electrical final_out;
    input electrical tx_p_src, tx_n_src;
    parameter real vbias = 0.9;   // output midpoint
    parameter real vamp  = 0.8;   // output swing
    parameter real gain  = 5.0;   // differential gain
    parameter real vth   = 0.0;   // differential threshold
    real v_diff;
    analog begin
      v_diff = V(tx_p_src) - V(tx_n_src);
      V(final_out) <+ vbias + vamp * tanh(gain * (v_diff - vth));
    end
  endmodule

Tune the parameter values to match the SerDes RX behavior.
Output ONLY the corrected Verilog-AMS module. No explanations."""

                try:
                    pass3_va = agent.chat(system_prompt, correction_prompt)

                    if "```" in pass3_va:
                        code_lines = []
                        in_fence = False
                        for line in pass3_va.split('\n'):
                            if line.strip().startswith('```'):
                                in_fence = not in_fence
                                continue
                            if in_fence or (not in_fence and 'module ' in line):
                                code_lines.append(line)
                        pass3_va = '\n'.join(code_lines)

                    if "module " in pass3_va:
                        module_start = pass3_va.find("module ")
                        if module_start > 0:
                            pass3_va = pass3_va[module_start:]

                    if "endmodule" in pass3_va:
                        pass3_va = pass3_va[:pass3_va.rfind("endmodule") + len("endmodule")]

                    if "`include" not in pass3_va and "module " in pass3_va:
                        pass3_va = "`include \"disciplines.vams\"\n\n" + pass3_va

                    pass3_va = fix_openvaf_compatibility(pass3_va)

                    passed_retry, metrics_retry, _ = validate_module(
                        module_name, pass3_va, netlist_text, block_info, output_dir
                    )

                    if passed_retry:
                        print(f" {Colors.GREEN}✓ FIXED{Colors.END} (err={metrics_retry['max_abs_error']:.2e})")
                        final_va     = pass3_va
                        final_source = "pass3_corrected"

                        pass3_dir = output_dir / "pass3"
                        pass3_dir.mkdir(parents=True, exist_ok=True)
                        (pass3_dir / f"{module_name}.va").write_text(pass3_va)

                    else:
                        print(f" {Colors.RED}✗ Still failing{Colors.END}, using baseline")
                        final_va     = baseline_va
                        final_source = "baseline_fallback"

                except Exception as e:
                    print(f" {Colors.RED}✗{Colors.END} Correction failed: {e}")
                    final_va     = baseline_va
                    final_source = "baseline_fallback"

    # Step 3: Save final result
    print_step(3, 3, "Saving final model...")

    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / f"{module_name}.va"
    final_path.write_text(final_va)

    print_success(f"Final model saved: {final_path}")
    print_info(f"Source: {final_source}")

    # Compile final .va → .osdi with OpenVAF
    import subprocess, shutil
    osdi_path = final_path.with_suffix('.osdi')
    openvaf_bin = shutil.which("openvaf")
    if openvaf_bin:
        print(f"\n{Colors.BOLD}Compiling with OpenVAF...{Colors.END}")
        try:
            result = subprocess.run(
                [openvaf_bin, str(final_path)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                # OpenVAF writes .osdi next to the .va file
                if osdi_path.exists():
                    print_success(f"OSDI compiled: {osdi_path}")
                else:
                    print_success(f"OpenVAF succeeded (exit 0)")
            else:
                print_warning(f"OpenVAF compilation failed (exit {result.returncode}):")
                if result.stderr:
                    print(result.stderr[:500])
        except subprocess.TimeoutExpired:
            print_warning("OpenVAF timed out after 120 s")
        except Exception as e:
            print_warning(f"OpenVAF error: {e}")
    else:
        print_warning("openvaf not found on PATH — skipping OSDI compilation")

    # Summary
    print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*80}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.GREEN}System-Level Model Extraction Complete!{Colors.END}")
    print(f"{Colors.BOLD}{Colors.GREEN}{'='*80}{Colors.END}\n")

    print(f"{Colors.BOLD}Results:{Colors.END}")
    print(f"  • Input netlist: {netlist_path}")
    print(f"  • System I/O: {', '.join(inputs)} → {', '.join(outputs)}")
    print(f"  • Models generated: 1 (not 10!)")
    print(f"  • Final model: {final_path}")
    print(f"  • OSDI binary: {osdi_path if osdi_path.exists() else '(not compiled)'}")
    print(f"  • Source: {final_source}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_error("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
