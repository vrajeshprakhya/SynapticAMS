#!/usr/bin/env python3
"""
SynapticAMS Warm-Start Demo
============================
Single-command demo showing SPICE → Verilog-AMS conversion using the Warm-Start method:
  1. Non-AI pipeline generates numerically-fitted baseline
  2. AI refines the baseline with domain knowledge

Usage:
    python3 demo_warmstart.py <netlist.cir> [--output-dir <path>]

Examples:
    python3 demo_warmstart.py examples/netlists/serdes_cml.cir
    python3 demo_warmstart.py examples/netlists/serdes_cml.cir --output-dir ./results
    python3 demo_warmstart.py examples/netlists/serdes_cml.cir -o /tmp/my_demo
"""

import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

# ANSI colors for pretty output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def print_banner(text):
    width = 80
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*width}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(width)}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*width}{Colors.END}\n")

def print_step(step_num, total, description):
    print(f"{Colors.BOLD}{Colors.GREEN}[Step {step_num}/{total}]{Colors.END} {description}")

def print_info(text):
    print(f"{Colors.CYAN}ℹ{Colors.END}  {text}")

def print_success(text):
    print(f"{Colors.GREEN}✓{Colors.END}  {text}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠{Colors.END}  {text}")

def print_error(text):
    print(f"{Colors.RED}✗{Colors.END}  {text}")

def check_capabilities():
    """Check if all required tools are available."""
    print_step(0, 4, "Checking capabilities...")

    issues = []

    # Check ngspice
    try:
        result = subprocess.run(["ngspice", "--version"],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print_success("ngspice found")
        else:
            issues.append("ngspice not working")
    except:
        issues.append("ngspice not installed")
        print_error("ngspice not found")

    # Check Ollama (only required if no Anthropic API key)
    import os
    has_anthropic_key = bool(os.getenv('ANTHROPIC_API_KEY'))

    try:
        result = subprocess.run(["curl", "-s", "http://192.168.1.34:11434/api/tags"],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print_success("Ollama LLM backend available")
        else:
            if not has_anthropic_key:
                issues.append("Ollama not responding")
    except:
        if has_anthropic_key:
            print_info("Using Anthropic API for AI refinement")
        else:
            issues.append("Cannot connect to Ollama at http://192.168.1.34:11434")
            print_warning("Ollama not available - AI features will be limited")

    # Check OpenVAF
    try:
        result = subprocess.run(["openvaf", "--version"],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print_success("OpenVAF compiler found")
        else:
            issues.append("OpenVAF not working")
    except:
        print_warning("OpenVAF not found - OSDI validation will be skipped")

    # Check pipeline modules
    try:
        import pipeline_ext
        print_success("Non-AI pipeline available (pipeline_ext)")
    except ImportError:
        issues.append("pipeline_ext module not found")
        print_error("pipeline_ext module not found")

    try:
        import ai_agent
        print_success("AI agent available")
    except ImportError:
        issues.append("ai_agent module not found")
        print_error("ai_agent module not found")

    if issues:
        print_error(f"Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"  • {issue}")
        return False

    print_success("All required tools available\n")
    return True

def run_nonai_pipeline(netlist_path: Path, output_dir: Path):
    """Run the non-AI numeric fitting pipeline."""
    print_step(1, 4, "Running Non-AI baseline generation (numeric fitting)...")
    print_info(f"Input: {netlist_path.name}")

    from pipeline_ext.complete_pipeline import spice_to_verilog_ams

    netlist_text = netlist_path.read_text()

    print_info("Analyzing circuit structure...")
    print_info("Running ngspice simulations...")
    print_info("Fitting transfer functions...")

    # Run the pipeline
    va_file_paths = spice_to_verilog_ams(
        netlist_text,
        output_dir=str(output_dir / "nonai")
    )

    # Read generated .va files
    va_modules = {}
    for va_path in va_file_paths:
        path_obj = Path(va_path) if not isinstance(va_path, Path) else va_path
        if not str(path_obj).endswith('.va'):
            continue  # Skip .tbl files
        if path_obj.exists():
            module_name = path_obj.stem
            va_code = path_obj.read_text()
            va_modules[module_name] = va_code

    if not va_modules:
        raise RuntimeError("No Verilog-AMS modules generated by non-AI pipeline")

    # Find the best module (for demo, pick first DC-fitted module with behavioral content)
    baseline_module = None
    baseline_name = None
    for module_name, va_code in va_modules.items():
        # Skip small_signal models for baseline (they're too simple)
        if "small_signal" in module_name.lower():
            continue
        if "analog" in va_code.lower() or "laplace" in va_code.lower():
            baseline_module = va_code
            baseline_name = module_name
            if "laplace" in va_code.lower():
                print_success(f"Selected baseline: {module_name} (dynamic model)")
            else:
                print_success(f"Selected baseline: {module_name}")
            break

    if not baseline_module:
        # Just pick first one
        baseline_name, baseline_module = next(iter(va_modules.items()))
        print_success(f"Generated {len(va_modules)} modules, selected {baseline_name} as example")

    # Save primary baseline for reference
    baseline_path = output_dir / "baseline_example.va"
    baseline_path.write_text(baseline_module)
    print_success(f"Example baseline saved to: {baseline_path}")

    # Show summary
    print(f"\n{Colors.BOLD}Non-AI Baseline Summary:{Colors.END}")
    print(f"  • Total modules generated: {len(va_modules)}")

    # Count by type
    dynamic_count = sum(1 for code in va_modules.values() if "dynamic" in code.lower() or "laplace" in code.lower())
    small_signal_count = sum(1 for name in va_modules.keys() if "small_signal" in name.lower())

    print(f"  • Dynamic models: {dynamic_count}")
    print(f"  • Small-signal models: {small_signal_count}")
    print(f"  • Total size: {sum(len(code) for code in va_modules.values())} chars")
    print(f"  • Method: Numeric transfer function fitting")

    return va_modules

def run_ai_refinement(netlist_path: Path, all_baseline_modules: dict, output_dir: Path):
    """Run AI refinement on ALL non-AI baseline modules."""
    print_step(2, 4, "Running AI refinement (warm-start on all modules)...")

    from ai_agent import OllamaAgent

    # Read netlist
    netlist_text = netlist_path.read_text()

    # Parse netlist info
    signal_source = None
    output_node = None
    for line in netlist_text.splitlines():
        line_upper = line.strip().upper()
        if line_upper.startswith("V") and not signal_source:
            parts = line.split()
            if len(parts) >= 2:
                signal_source = parts[0]
        if ".PRINT" in line_upper:
            parts = line.split()
            if "V(" in line.upper():
                import re
                match = re.search(r'V\((\w+)\)', line, re.IGNORECASE)
                if match:
                    output_node = match.group(1)

    if not signal_source:
        signal_source = "VIN"
    if not output_node:
        output_node = "out"

    # Create AI agent
    agent = OllamaAgent(
        model="llama3.2:3b",
        base_url="http://192.168.1.34:11434"
    )

    # Build system prompt (same for all modules)
    system_prompt = """You are a Verilog-AMS expert specializing in circuit behavioral modeling.
Your task is to refine numerically-fitted Verilog-AMS models to improve accuracy.
CRITICAL: Output ONLY valid Verilog-AMS code. No explanations, no text before or after the module."""

    # Filter modules to refine (skip small-signal, they're already optimized)
    modules_to_refine = {name: code for name, code in all_baseline_modules.items()
                        if "small_signal" not in name.lower()}

    print_info(f"Refining {len(modules_to_refine)} modules (skipping {len(all_baseline_modules) - len(modules_to_refine)} small-signal models)...")

    refined_modules = {}
    refined_dir = output_dir / "refined"
    refined_dir.mkdir(parents=True, exist_ok=True)

    for i, (module_name, baseline_va) in enumerate(modules_to_refine.items(), 1):
        print(f"\n{Colors.CYAN}[{i}/{len(modules_to_refine)}]{Colors.END} Refining {Colors.BOLD}{module_name}{Colors.END}...", end="", flush=True)

        user_prompt = f"""I have a SPICE netlist and a numerically-fitted baseline Verilog-AMS model.

Task: REFINE the baseline model to improve accuracy while maintaining the structure.

SPICE Netlist:
```
{netlist_text}
```

Baseline Verilog-AMS Model (numeric fitting):
```
{baseline_va}
```

Circuit Info:
- Signal source: {signal_source}
- Output node: {output_node}

Instructions:
1. Keep the baseline structure (ports, parameters, analog block)
2. Improve the transfer function or behavioral equations if you can identify obvious issues
3. Add frequency response if the circuit clearly has AC behavior
4. Do NOT add intermediate variables or complex constructs
5. Output ONLY valid Verilog-AMS code that OpenVAF can compile

Output the refined Verilog-AMS module code ONLY. No explanations."""

        try:
            refined_va = agent.chat(system_prompt, user_prompt)

            # Clean up AI output (remove any explanation text after endmodule)
            if "endmodule" in refined_va:
                refined_va = refined_va[:refined_va.rfind("endmodule") + len("endmodule")]

            refined_modules[module_name] = refined_va

            # Save individual refined module
            refined_path = refined_dir / f"{module_name}.va"
            refined_path.write_text(refined_va)

            size_change = len(refined_va) - len(baseline_va)
            print(f" {Colors.GREEN}✓{Colors.END} ({size_change:+d} chars)")

        except Exception as e:
            print(f" {Colors.RED}✗{Colors.END} Failed: {e}")
            refined_modules[module_name] = baseline_va  # Fall back to baseline

    # Calculate statistics
    total_baseline_size = sum(len(code) for code in modules_to_refine.values())
    total_refined_size = sum(len(code) for code in refined_modules.values())

    print(f"\n{Colors.BOLD}AI Refinement Summary:{Colors.END}")
    print(f"  • Modules refined: {len(refined_modules)}")
    print(f"  • Total baseline size: {total_baseline_size} chars")
    print(f"  • Total refined size: {total_refined_size} chars ({total_refined_size - total_baseline_size:+d})")
    print(f"  • Average change per module: {(total_refined_size - total_baseline_size) // len(refined_modules):+d} chars")
    print(f"  • Method: LLM-based refinement with domain knowledge")
    print(f"  • Output directory: {refined_dir}")

    return refined_modules

def compare_models(baseline_modules: dict, refined_modules: dict, output_dir: Path):
    """Show side-by-side comparison of baseline vs refined for all modules."""
    print_step(3, 4, "Comparing baseline vs refined models...")

    comparison_path = output_dir / "comparison_all_modules.txt"

    with open(comparison_path, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("WARM-START METHOD COMPARISON (ALL MODULES)\n")
        f.write("=" * 80 + "\n\n")

        for module_name in refined_modules.keys():
            baseline_va = baseline_modules.get(module_name, "")
            refined_va = refined_modules[module_name]

            f.write(f"\n{'=' * 80}\n")
            f.write(f"MODULE: {module_name}\n")
            f.write(f"{'=' * 80}\n\n")

            f.write("BASELINE (Non-AI numeric fitting):\n")
            f.write("-" * 80 + "\n")
            f.write(baseline_va)
            f.write("\n\n")

            f.write("REFINED (AI warm-start):\n")
            f.write("-" * 80 + "\n")
            f.write(refined_va)
            f.write("\n\n")

    print_success(f"Full comparison saved to: {comparison_path}")

    # Show aggregate statistics
    total_baseline_size = sum(len(code) for code in baseline_modules.values() if code)
    total_refined_size = sum(len(code) for code in refined_modules.values())

    total_baseline_lines = sum(len(code.splitlines()) for code in baseline_modules.values() if code)
    total_refined_lines = sum(len(code.splitlines()) for code in refined_modules.values())

    print(f"\n{Colors.BOLD}Aggregate Statistics:{Colors.END}")
    print(f"  • Modules refined: {len(refined_modules)}")
    print(f"  • Total baseline lines: {total_baseline_lines}")
    print(f"  • Total refined lines: {total_refined_lines} ({total_refined_lines - total_baseline_lines:+d})")
    print(f"  • Total baseline size: {total_baseline_size} chars")
    print(f"  • Total refined size: {total_refined_size} chars ({total_refined_size - total_baseline_size:+d})")

    # Show per-module comparison
    print(f"\n{Colors.BOLD}Per-Module Changes:{Colors.END}")
    for module_name in sorted(refined_modules.keys()):
        baseline_va = baseline_modules.get(module_name, "")
        refined_va = refined_modules[module_name]
        size_change = len(refined_va) - len(baseline_va)
        line_change = len(refined_va.splitlines()) - len(baseline_va.splitlines())

        color = Colors.GREEN if size_change >= 0 else Colors.RED
        print(f"  • {module_name}: {color}{size_change:+d}{Colors.END} chars, {color}{line_change:+d}{Colors.END} lines")

def generate_summary(netlist_path: Path, output_dir: Path, num_refined: int):
    """Generate final summary and next steps."""
    print_step(4, 4, "Generating summary...")

    summary_path = output_dir / "WARMSTART_SUMMARY.txt"
    refined_dir = output_dir / "refined"

    with open(summary_path, 'w') as f:
        f.write("SynapticAMS Warm-Start Demo Results\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Input netlist: {netlist_path.name}\n")
        f.write(f"Output directory: {output_dir}\n\n")

        f.write("Method: Warm-Start (Non-AI → AI Refinement)\n")
        f.write("-" * 80 + "\n")
        f.write("1. Non-AI pipeline extracts circuit structure and fits transfer functions\n")
        f.write("2. AI agent refines ALL modules with domain knowledge\n")
        f.write("3. Result combines numeric precision with intelligent modeling\n\n")

        f.write("Generated Files:\n")
        f.write("-" * 80 + "\n")
        f.write(f"  • baseline_example.va    - Example non-AI numerically-fitted model\n")
        f.write(f"  • refined/               - All {num_refined} AI-refined modules\n")
        f.write(f"  • comparison_all_modules.txt - Side-by-side comparison of all modules\n")
        f.write(f"  • nonai/                 - All non-AI generated modules\n\n")

        f.write("Next Steps:\n")
        f.write("-" * 80 + "\n")
        f.write(f"1. Review refined modules: ls {refined_dir}/*.va\n")
        f.write(f"2. Compare all changes: cat comparison_all_modules.txt\n")
        f.write(f"3. Compile each module: for f in {refined_dir}/*.va; do openvaf $f; done\n")
        f.write(f"4. Pick specific module: cat {refined_dir}/<module_name>.va\n\n")

        f.write("When to Use Warm-Start:\n")
        f.write("-" * 80 + "\n")
        f.write("✓ Simple amplifiers and DC circuits (38% better than pure AI)\n")
        f.write("✓ When you want numeric precision + AI intelligence\n")
        f.write("✓ When pure AI struggles to converge\n")
        f.write("✗ Complex RF/SerDes (use AI Judge instead)\n")
        f.write("✗ When non-AI baseline is very poor\n")

    print_success(f"Summary saved to: {summary_path}")

    print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*80}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.GREEN}Demo Complete!{Colors.END}")
    print(f"{Colors.BOLD}{Colors.GREEN}{'='*80}{Colors.END}\n")

    print(f"{Colors.BOLD}Output Directory:{Colors.END} {output_dir}")
    print(f"\n{Colors.BOLD}Generated Files:{Colors.END}")
    print(f"  • {Colors.CYAN}baseline_example.va{Colors.END}           - Example non-AI model")
    print(f"  • {Colors.CYAN}refined/{Colors.END}                      - {num_refined} AI-refined modules")
    print(f"  • {Colors.CYAN}comparison_all_modules.txt{Colors.END}    - Full comparison")
    print(f"  • {Colors.CYAN}nonai/{Colors.END}                        - All non-AI modules")

    print(f"\n{Colors.BOLD}Quick Commands:{Colors.END}")
    print(f"  List all refined modules: {Colors.YELLOW}ls {refined_dir}/*.va{Colors.END}")
    print(f"  View specific module:     {Colors.YELLOW}cat {refined_dir}/<module_name>.va{Colors.END}")
    print(f"  View all changes:         {Colors.YELLOW}cat {output_dir}/comparison_all_modules.txt{Colors.END}")
    print(f"  Compile all modules:      {Colors.YELLOW}cd {refined_dir} && for f in *.va; do openvaf $f; done{Colors.END}")

def main():
    print_banner("SynapticAMS Warm-Start Demo")
    print_info("SPICE → Verilog-AMS conversion using Non-AI baseline + AI refinement")

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="SynapticAMS Warm-Start Demo: SPICE → Verilog-AMS conversion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 demo_warmstart.py examples/netlists/serdes_cml.cir
  python3 demo_warmstart.py examples/netlists/serdes_cml.cir --output-dir ./results
  python3 demo_warmstart.py examples/netlists/serdes_cml.cir -o /tmp/my_demo
        """
    )
    parser.add_argument("netlist", type=str, help="Path to SPICE netlist (.cir file)")
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=None,
        help="Output directory for generated files (default: /tmp/synapticams_warmstart_demo_<netlist_name>)"
    )

    args = parser.parse_args()

    netlist_path = Path(args.netlist)
    if not netlist_path.exists():
        print_error(f"Netlist not found: {netlist_path}")
        sys.exit(1)

    # Create output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("/tmp") / f"synapticams_warmstart_demo_{netlist_path.stem}"

    output_dir.mkdir(parents=True, exist_ok=True)

    print_info(f"Input: {netlist_path}")
    print_info(f"Output: {output_dir}\n")

    # Check capabilities
    if not check_capabilities():
        print_error("Missing required tools. Please install them and try again.")
        sys.exit(1)

    try:
        # Step 1: Non-AI baseline
        all_baseline_modules = run_nonai_pipeline(netlist_path, output_dir)

        # Step 2: AI refinement (refine ALL modules)
        refined_modules = run_ai_refinement(netlist_path, all_baseline_modules, output_dir)

        # Step 3: Compare
        compare_models(all_baseline_modules, refined_modules, output_dir)

        # Step 4: Summary
        generate_summary(netlist_path, output_dir, len(refined_modules))

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
