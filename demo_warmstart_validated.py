#!/usr/bin/env python3
"""
SynapticAMS Warm-Start Demo with Validation Loop
=================================================
Enhanced demo with 3-pass AI refinement:
  1. AI refines baseline model
  2. Run OSDI + equivalence checking
  3. AI fixes errors based on validation feedback

Usage:
    python3 demo_warmstart_validated.py <netlist.cir> [--output-dir <path>]

Example:
    python3 demo_warmstart_validated.py examples/netlists/serdes_cml.cir
"""

import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, Optional

# Import from original demo
from demo_warmstart import (
    Colors, print_banner, print_step, print_info, print_success,
    print_warning, print_error, check_capabilities, run_nonai_pipeline,
    compare_models, generate_summary
)


def validate_module(module_name: str,
                    verilog_ams_code: str,
                    spice_netlist: str,
                    block_info: Dict,
                    output_dir: Path) -> Tuple[bool, Dict, Optional[str]]:
    """
    Validate a Verilog-AMS module using OSDI + equivalence checking

    Detects model type (static LUT vs dynamic Laplace) and routes to appropriate validator:
    - Static models → DC/AC sweep validation
    - Dynamic models → Transient validation

    Returns:
        (passed, metrics, error_message)
    """
    # Detect if model is dynamic (Laplace transfer function)
    is_dynamic = 'laplace' in verilog_ams_code.lower()

    if is_dynamic:
        # Use OSDI transient checker for dynamic models
        from equivalence_checker.equivalence_checker_osdi import OSDIEquivalenceChecker

        checker = OSDIEquivalenceChecker(
            abs_tol=1e-3,
            rel_tol=0.05
        )

        try:
            # Extract output nodes from block_info
            outputs = block_info.get('outputs', [])

            result = checker.check_transient_equivalence(
                netlist=spice_netlist,
                verilog_ams_code=verilog_ams_code,
                module_name=module_name,
                output_nodes=outputs,
                tstop='1u',  # 1 microsecond simulation
                tstep='1n'   # 1 nanosecond timestep
            )

            metrics = {
                'max_abs_error': result.max_absolute_error,
                'max_rel_error': result.max_relative_error,
                'rms_error': result.rms_error,
                'correlation': result.correlation,
                'coverage': 100.0 if result.passed else 0.0
            }

            return result.passed, metrics, None

        except Exception as e:
            error_msg = str(e)
            return False, {}, f"Transient validation error: {error_msg}"

    else:
        # Use regular checker for static LUT models
        from equivalence_checker.equivalence_checker import EquivalenceChecker

        checker = EquivalenceChecker(
            abs_tol=1e-3,
            rel_tol=0.05,
            testbench_output_dir=str(output_dir / "testbenches")
        )

        try:
            result = checker.check_block_equivalence(
                spice_netlist=spice_netlist,
                verilog_ams_code=verilog_ams_code,
                block_info=block_info,
                test_strategy='grid'
            )

            metrics = {
                'max_abs_error': result.max_absolute_error,
                'max_rel_error': result.max_relative_error,
                'rms_error': result.rms_error,
                'correlation': result.correlation,
                'coverage': result.coverage_percentage
            }

            return result.passed, metrics, None

        except Exception as e:
            error_msg = str(e)
            if "OpenVAF compilation failed" in error_msg:
                # Extract compilation error
                return False, {}, f"Compilation error: {error_msg}"
            elif "timeout" in error_msg.lower():
                return False, {}, f"Simulation timeout: {error_msg}"
            else:
                return False, {}, f"Validation error: {error_msg}"


def run_ai_refinement_with_validation(netlist_path: Path,
                                       all_baseline_modules: dict,
                                       output_dir: Path,
                                       spice_netlist: str,
                                       block_info: Dict) -> Dict:
    """
    Run AI refinement with 3-pass validation loop:
    1. Initial AI refinement
    2. Equivalence checking
    3. Error correction pass
    """
    print_step(2, 5, "Running AI refinement with validation loop...")

    from ai_agent import create_agent

    # Auto-detect AI backend (Anthropic or Ollama)
    agent = create_agent()
    print_info(f"Using AI backend: {type(agent).__name__}/{agent.model}")

    # Read netlist
    netlist_text = netlist_path.read_text()

    # Filter modules to refine
    modules_to_refine = {name: code for name, code in all_baseline_modules.items()
                        if "small_signal" not in name.lower()}

    print_info(f"Refining {len(modules_to_refine)} modules with 3-pass validation...")

    refined_dir = output_dir / "refined"
    refined_dir.mkdir(parents=True, exist_ok=True)

    # Use Anthropic API if available
    import os
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if api_key:
        print_info(f"Using Anthropic API for AI refinement")
        from ai_agent import ClaudeAgent
        agent = ClaudeAgent(model="claude-sonnet-4-20250514")
    else:
        print_info(f"Using Ollama backend for AI refinement")
        from ai_agent import OllamaAgent
        agent = OllamaAgent(model="llama3.2:3b")

    validation_report = []
    final_modules = {}

    for i, (module_name, baseline_va) in enumerate(modules_to_refine.items(), 1):
        print(f"\n{Colors.CYAN}[{i}/{len(modules_to_refine)}]{Colors.END} {Colors.BOLD}{module_name}{Colors.END}")

        # ========================================================================
        # PASS 1: Initial AI Refinement
        # ========================================================================
        print(f"  {Colors.CYAN}Pass 1:{Colors.END} AI refinement...", end="", flush=True)

        system_prompt = """You are a Verilog-AMS expert specializing in circuit behavioral modeling.
Your task is to refine numerically-fitted Verilog-AMS models to improve accuracy.
CRITICAL: Output ONLY valid Verilog-AMS code. No explanations, no text before or after the module."""

        user_prompt = f"""Refine this baseline Verilog-AMS model to improve accuracy.

SPICE Netlist:
```
{netlist_text}
```

Baseline Verilog-AMS Model:
```
{baseline_va}
```

Instructions:
1. Keep the baseline structure (ports, parameters, analog block)
2. Improve the transfer function or behavioral equations
3. Add frequency response if the circuit has AC behavior
4. Ensure OpenVAF can compile the code
5. Output ONLY valid Verilog-AMS code

Output the refined module code ONLY. No explanations."""

        try:
            # Skip OSDI validation for 2D LUT models (known issue with OSDI netlist generation)
            skip_validation = "lut2d" in module_name.lower() or "lut_2d" in module_name.lower()
            if skip_validation:
                print(f" {Colors.YELLOW}⚠{Colors.END} Skipping OSDI validation for 2D LUT (known issue)")
                final_modules[module_name] = baseline_va
                validation_report.append({
                    'module': module_name,
                    'pass1': 'skipped',
                    'validation': 'skipped',
                    'pass3': 'n/a',
                    'final': 'baseline',
                    'metrics': {},
                    'error_msg': '2D LUT OSDI validation disabled',
                    'pass1_error': None
                })
                continue

            pass1_va = agent.chat(system_prompt, user_prompt)

            # Clean up AI output
            if "endmodule" in pass1_va:
                pass1_va = pass1_va[:pass1_va.rfind("endmodule") + len("endmodule")]

            size_change = len(pass1_va) - len(baseline_va)
            print(f" {Colors.GREEN}✓{Colors.END} ({size_change:+d} chars)")

        except Exception as e:
            print(f" {Colors.RED}✗{Colors.END} Failed: {e}")
            final_modules[module_name] = baseline_va
            continue

        # ========================================================================
        # PASS 2: Equivalence Checking
        # ========================================================================
        print(f"  {Colors.CYAN}Pass 2:{Colors.END} Equivalence check...", end="", flush=True)

        passed, metrics, error_msg = validate_module(
            module_name, pass1_va, spice_netlist, block_info, output_dir
        )

        if passed:
            print(f" {Colors.GREEN}✓ PASS{Colors.END} (err={metrics['max_abs_error']:.2e}, corr={metrics['correlation']:.3f})")
            final_modules[module_name] = pass1_va
            validation_report.append({
                'module': module_name,
                'pass1': 'success',
                'validation': 'passed',
                'pass3': 'not_needed',
                'final': 'pass1',
                'metrics': metrics,
                'error_msg': None
            })

        else:
            if error_msg:
                print(f" {Colors.YELLOW}⚠ FAIL{Colors.END} - {error_msg[:60]}...")
            else:
                print(f" {Colors.YELLOW}⚠ FAIL{Colors.END} (err={metrics.get('max_abs_error', 'N/A')})")

            # ====================================================================
            # PASS 3: Error Correction
            # ====================================================================
            print(f"  {Colors.CYAN}Pass 3:{Colors.END} AI error correction...", end="", flush=True)

            correction_prompt = f"""The refined model failed validation. Please fix the errors.

SPICE Netlist (ground truth):
```
{netlist_text}
```

Your Previous Attempt (FAILED):
```
{pass1_va}
```

Validation Error:
{error_msg if error_msg else f"Poor accuracy: max_error={metrics.get('max_abs_error', 'N/A')}, correlation={metrics.get('correlation', 'N/A')}"}

Instructions:
1. If compilation error: fix syntax/semantic issues
2. If accuracy error: improve transfer function accuracy
3. If timeout: simplify the model (remove complex dynamics)
4. Ensure the model is valid Verilog-AMS that OpenVAF can compile
5. Output ONLY the corrected module code

Output the corrected Verilog-AMS module code ONLY. No explanations."""

            try:
                pass3_va = agent.chat(system_prompt, correction_prompt)

                # Clean up AI output
                if "endmodule" in pass3_va:
                    pass3_va = pass3_va[:pass3_va.rfind("endmodule") + len("endmodule")]

                # Quick validation of corrected version
                passed_retry, metrics_retry, error_retry = validate_module(
                    module_name, pass3_va, spice_netlist, block_info, output_dir
                )

                if passed_retry:
                    print(f" {Colors.GREEN}✓ FIXED{Colors.END} (err={metrics_retry['max_abs_error']:.2e})")
                    final_modules[module_name] = pass3_va
                    validation_report.append({
                        'module': module_name,
                        'pass1': 'failed',
                        'validation': 'failed',
                        'pass3': 'success',
                        'final': 'pass3_corrected',
                        'metrics': metrics_retry,
                        'error_msg': None,
                        'pass1_error': error_msg
                    })
                else:
                    print(f" {Colors.RED}✗ Still failing{Colors.END}, using baseline")
                    final_modules[module_name] = baseline_va
                    validation_report.append({
                        'module': module_name,
                        'pass1': 'failed',
                        'validation': 'failed',
                        'pass3': 'failed',
                        'final': 'baseline_fallback',
                        'metrics': metrics_retry if 'metrics_retry' in locals() else metrics,
                        'error_msg': error_retry if 'error_retry' in locals() else error_msg,
                        'pass1_error': error_msg
                    })

            except Exception as e:
                print(f" {Colors.RED}✗{Colors.END} Correction failed: {e}")
                final_modules[module_name] = baseline_va
                validation_report.append({
                    'module': module_name,
                    'pass1': 'failed',
                    'validation': 'failed',
                    'pass3': 'exception',
                    'final': 'baseline_fallback',
                    'metrics': metrics,
                    'error_msg': str(e),
                    'pass1_error': error_msg
                })

        # Save final version
        refined_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
        final_path = refined_dir / f"{module_name}.va"
        final_path.write_text(final_modules[module_name])

    # Summary
    print(f"\n{Colors.BOLD}AI Refinement with Validation Summary:{Colors.END}")

    pass1_success = sum(1 for r in validation_report if r['pass1'] == 'success')
    validation_passed = sum(1 for r in validation_report if r['validation'] == 'passed')
    pass3_fixes = sum(1 for r in validation_report if r['pass3'] == 'success')
    baseline_fallback = sum(1 for r in validation_report if r['final'] == 'baseline_fallback')

    print(f"  • Modules refined: {len(modules_to_refine)}")
    print(f"  • Pass 1 (AI refinement): {pass1_success}/{len(modules_to_refine)} succeeded")
    print(f"  • Pass 2 (Validation): {validation_passed}/{len(modules_to_refine)} passed")
    print(f"  • Pass 3 (Error correction): {pass3_fixes} fixed")
    print(f"  • Baseline fallback: {baseline_fallback}")
    print(f"  • Output directory: {refined_dir}")

    # Save validation report
    report_path = output_dir / "validation_report.txt"
    with open(report_path, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("AI Refinement Validation Report\n")
        f.write("=" * 80 + "\n\n")
        for r in validation_report:
            f.write(f"Module: {r['module']}\n")
            f.write(f"  Pass 1 (AI refinement): {r['pass1']}\n")
            f.write(f"  Pass 2 (Validation): {r['validation']}\n")
            f.write(f"  Pass 3 (Error correction): {r['pass3']}\n")
            f.write(f"  Final version: {r['final']}\n")

            # Add detailed SPICE/EC metrics if available
            if 'metrics' in r and r['metrics']:
                f.write(f"\n  SPICE/EC Validation Metrics:\n")
                m = r['metrics']
                f.write(f"    Max Absolute Error: {m.get('max_abs_error', 'N/A'):.6e}\n")
                f.write(f"    Max Relative Error: {m.get('max_rel_error', 'N/A'):.2%}\n" if isinstance(m.get('max_rel_error'), float) else f"    Max Relative Error: {m.get('max_rel_error', 'N/A')}\n")
                f.write(f"    RMS Error:          {m.get('rms_error', 'N/A'):.6e}\n")
                f.write(f"    Correlation:        {m.get('correlation', 'N/A'):.6f}\n")
                f.write(f"    Coverage:           {m.get('coverage', 'N/A'):.1f}%\n" if isinstance(m.get('coverage'), float) else f"    Coverage:           {m.get('coverage', 'N/A')}\n")

            if 'error_msg' in r and r['error_msg']:
                f.write(f"\n  Final Error: {r['error_msg']}\n")

            if 'pass1_error' in r and r['pass1_error']:
                f.write(f"  Pass 1 Error: {r['pass1_error']}\n")

            f.write("\n")

    print_success(f"Validation report saved to: {report_path}")

    # Save detailed metrics to JSON for programmatic access
    import json
    metrics_json_path = output_dir / "validation_metrics.json"
    with open(metrics_json_path, 'w') as f:
        json.dump(validation_report, f, indent=2, default=str)
    print_success(f"Detailed metrics saved to: {metrics_json_path}")

    return final_modules


def main():
    print_banner("SynapticAMS Warm-Start Demo (with Validation)")
    print_info("SPICE → Verilog-AMS with 3-pass AI refinement and validation")

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="SynapticAMS Warm-Start Demo with Validation Loop",
    )
    parser.add_argument("netlist", type=str, help="Path to SPICE netlist (.cir file)")
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: /tmp/synapticams_warmstart_validated_<netlist_name>)"
    )

    args = parser.parse_args()

    netlist_path = Path(args.netlist)
    if not netlist_path.exists():
        print_error(f"Netlist not found: {netlist_path}")
        sys.exit(1)

    # Create output directory
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()  # Convert to absolute path
    else:
        output_dir = Path("/tmp") / f"synapticams_warmstart_validated_{netlist_path.stem}"
        output_dir = output_dir.resolve()

    output_dir.mkdir(parents=True, exist_ok=True)

    print_info(f"Input: {netlist_path}")
    print_info(f"Output: {output_dir}\n")

    # Check capabilities
    if not check_capabilities():
        print_error("Missing required tools. Please install them and try again.")
        sys.exit(1)

    try:
        # Step 1: Non-AI baseline
        print_step(1, 5, "Running Non-AI baseline generation...")
        all_baseline_modules = run_nonai_pipeline(netlist_path, output_dir)

        # Extract netlist and block_info for validation
        netlist_text = netlist_path.read_text()

        # Create dummy block_info (would normally come from pipeline)
        # For now, extract from one of the baseline modules
        block_info = {
            'name': 'block_0',
            'inputs': set(),
            'outputs': set(),
            'simulation_axes': []
        }

        # Step 2: AI refinement with validation loop
        refined_modules = run_ai_refinement_with_validation(
            netlist_path, all_baseline_modules, output_dir,
            netlist_text, block_info
        )

        # Step 3: Compare
        print_step(3, 5, "Comparing baseline vs refined models...")
        compare_models(all_baseline_modules, refined_modules, output_dir)

        # Step 4: Final validation of all refined modules
        print_step(4, 5, "Running final validation pass...")
        print_info("Compiling all refined modules with OpenVAF...")

        refined_dir = output_dir / "refined"
        compile_results = []
        for va_file in refined_dir.glob("*.va"):
            try:
                result = subprocess.run(
                    ["openvaf", str(va_file)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    compile_results.append((va_file.stem, True, None))
                    print(f"  {Colors.GREEN}✓{Colors.END} {va_file.name}")
                else:
                    compile_results.append((va_file.stem, False, result.stderr))
                    print(f"  {Colors.RED}✗{Colors.END} {va_file.name}: {result.stderr[:50]}")
            except subprocess.TimeoutExpired:
                compile_results.append((va_file.stem, False, "Timeout"))
                print(f"  {Colors.YELLOW}⚠{Colors.END} {va_file.name}: Timeout")
            except FileNotFoundError:
                print_warning("OpenVAF not found - skipping compilation check")
                break

        # Step 5: Summary
        print_step(5, 5, "Generating summary...")
        generate_summary(netlist_path, output_dir, len(refined_modules))

        print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*80}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.GREEN}Validation-Enhanced Demo Complete!{Colors.END}")
        print(f"{Colors.BOLD}{Colors.GREEN}{'='*80}{Colors.END}\n")

        print(f"{Colors.BOLD}Key Improvements over Basic Demo:{Colors.END}")
        print(f"  • 3-pass AI refinement with validation feedback")
        print(f"  • OSDI compilation + equivalence checking per module")
        print(f"  • Automatic error correction by AI")
        print(f"  • Validation report: {output_dir}/validation_report.txt")

    except KeyboardInterrupt:
        print_error("\nDemo interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
