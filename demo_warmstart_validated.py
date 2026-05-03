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


def fix_openvaf_compatibility(verilog_ams_code):
    """
    Automatically fix common OpenVAF incompatibilities in AI-generated code.

    Fixes:
    - ALL Verilog-AMS macros (M_PI, M_TWO_PI, M_E, etc.) → numeric values
    - Laplace functions → Remove (comment out)
    - $random → 0
    - Undefined variables (s, laplace_s, etc.) → Remove
    - white_noise(), flicker_noise() → 0
    - Variable declarations in analog blocks → Move or comment out
    """
    import re

    code = verilog_ams_code

    # Fix 1: Replace ALL Verilog-AMS math macros with numeric values
    # Handle both `M_PI (with backtick) and M_PI (without backtick)
    macro_replacements = {
        r'`?M_PI\b': '3.141592653589793',
        r'`?M_TWO_PI\b': '6.283185307179586',  # 2*PI
        r'`?M_E\b': '2.718281828459045',
        r'`?M_LOG2E\b': '1.4426950408889634',
        r'`?M_LOG10E\b': '0.43429448190325176',
        r'`?M_LN2\b': '0.6931471805599453',
        r'`?M_LN10\b': '2.302585092994046',
        r'`?M_SQRT2\b': '1.4142135623730951',
        r'`?M_SQRT1_2\b': '0.7071067811865476',
    }
    for macro, value in macro_replacements.items():
        code = re.sub(macro, value, code)

    # Fix 2: Remove ALL Laplace function calls (comment them out)
    # Match laplace_nd(), laplace_zd(), laplace_zp(), laplace_np()
    code = re.sub(
        r'(\s*)(\w+)\s*=\s*laplace_[a-z]+\([^;]+\);',
        r'\1// REMOVED (OpenVAF unsupported): \2 = ...; // Using fallback\n\1\2 = 0.0;',
        code
    )

    # Fix 3: Remove zi_* functions
    code = re.sub(
        r'(\s*)(\w+)\s*=\s*zi_[a-z]+\([^;]+\);',
        r'\1// REMOVED (OpenVAF unsupported): \2 = ...\n\1\2 = 0.0;',
        code
    )

    # Fix 4: Replace $random with 0
    code = re.sub(r'\$random', '0.0', code)

    # Fix 5: Replace noise functions with 0
    code = re.sub(r'white_noise\([^)]+\)', '0.0', code)
    code = re.sub(r'flicker_noise\([^)]+\)', '0.0', code)

    # Fix 6: Comment out lines with undefined variables (s, laplace_s, omega_s, etc.)
    lines = code.split('\n')
    fixed_lines = []
    for line in lines:
        # Check for Laplace-domain variables: 's', 'laplace_s', 'omega_s'
        if re.search(r'\b(s|laplace_s|omega_s|jw)\s*[\*\/\+\-]|[\*\/\+\-]\s*\b(s|laplace_s|omega_s|jw)\b', line):
            if not line.strip().startswith('//'):
                fixed_lines.append('        // REMOVED (undefined Laplace variable): ' + line.strip())
                continue

        # Check for real declarations inside analog blocks (OpenVAF requires scope)
        if 'analog begin' not in line and re.search(r'^\s*real\s+\w+\s*;', line):
            # If we're inside analog block, this needs to be moved out
            # For now, comment it out to avoid compilation error
            if not line.strip().startswith('//'):
                fixed_lines.append('        // REMOVED (declaration in analog block): ' + line.strip())
                continue

        fixed_lines.append(line)
    code = '\n'.join(fixed_lines)

    # Fix 7: Replace limexp with exp
    code = re.sub(r'limexp\(', 'exp(', code)

    return code


def extract_module_ports(verilog_code: str) -> Tuple[list, list]:
    """
    Extract input and output ports from Verilog-AMS module code.

    Returns:
        (inputs, outputs) tuple of port name lists
    """
    import re

    inputs = []
    outputs = []

    # Find module declaration
    module_match = re.search(r'module\s+\w+\s*\((.*?)\);', verilog_code, re.DOTALL)
    if not module_match:
        return inputs, outputs

    ports_text = module_match.group(1)

    # Parse each port line
    for line in ports_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('//'):
            continue

        # Remove trailing comma
        line = line.rstrip(',')

        # Match: input/output electrical <name>
        port_match = re.match(r'(input|output)\s+electrical\s+(\w+)', line)
        if port_match:
            direction, name = port_match.groups()
            if direction == 'input':
                inputs.append(name)
            elif direction == 'output':
                outputs.append(name)

    return inputs, outputs


def is_ac_coupled_circuit(netlist_text: str) -> bool:
    """
    Detect if circuit is AC-coupled (SerDes, RF amplifier, etc.)

    Indicators:
    - Has AC sources (SIN, PULSE with AC component)
    - Has .AC or .TRAN analysis directives
    - Contains SerDes/RF keywords in comments
    - Has coupling capacitors

    Returns:
        True if circuit is AC-coupled and needs transient validation
    """
    import re

    netlist_upper = netlist_text.upper()

    # Check for AC sources (SIN, PULSE, AC)
    has_ac_source = bool(re.search(r'\b(SIN|PULSE|AC)\s*\(', netlist_text, re.I))

    # Check for AC/transient analysis directive
    has_ac_analysis = '.AC ' in netlist_upper or '.TRAN ' in netlist_upper

    # Check for SerDes/RF keywords
    rf_keywords = ['SERDES', 'CTLE', 'VGA', 'CDR', 'PLL', 'RF', 'MIXER', 'LNA']
    has_rf_keyword = any(kw in netlist_upper for kw in rf_keywords)

    # Check for coupling capacitors (C followed by "ac" or "couple")
    has_coupling_cap = bool(re.search(r'C\w*(AC|COUPL)', netlist_text, re.I))

    # Circuit is AC-coupled if it has AC sources AND analysis, OR has RF keywords
    return (has_ac_source and has_ac_analysis) or has_rf_keyword or has_coupling_cap


def validate_module(module_name: str,
                    verilog_ams_code: str,
                    spice_netlist: str,
                    block_info: Dict,
                    output_dir: Path) -> Tuple[bool, Dict, Optional[str]]:
    """
    Validate a Verilog-AMS module using OSDI + equivalence checking

    Smart validation mode selection:
    - AC-coupled circuits (SerDes, RF) → Transient validation
    - Dynamic models (with laplace) → Transient validation
    - Static models → DC sweep validation

    Returns:
        (passed, metrics, error_message)
    """
    # Detect circuit and model type
    is_ac_circuit = is_ac_coupled_circuit(spice_netlist)
    is_dynamic = 'laplace' in verilog_ams_code.lower()

    # Use transient validation for AC circuits or dynamic models
    use_transient = is_ac_circuit or is_dynamic

    if use_transient:
        # Use OSDI transient checker for dynamic models
        from equivalence_checker.equivalence_checker_osdi import OSDIEquivalenceChecker

        checker = OSDIEquivalenceChecker(
            abs_tol=1e-3,
            rel_tol=0.05
        )

        try:
            # Extract input and output nodes from block_info
            inputs = list(block_info.get('inputs', []))
            inputs_clean = [i.replace('net:', '') for i in inputs]
            outputs = list(block_info.get('outputs', []))
            outputs_clean = [o.replace('net:', '') for o in outputs]

            # Use shorter simulation time for SerDes (GHz signals)
            if is_ac_circuit:
                tstop = '10n'  # 10 nanoseconds (enough for multiple GHz cycles)
                tstep = '10p'  # 10 picoseconds
                mode_desc = "transient (AC-coupled/SerDes)"
            else:
                tstop = '1u'   # 1 microsecond for general dynamic models
                tstep = '1n'   # 1 nanosecond
                mode_desc = "transient (dynamic)"

            result = checker.check_transient_equivalence(
                netlist=spice_netlist,
                verilog_ams_code=verilog_ams_code,
                module_name=module_name,
                input_names=inputs_clean,
                output_names=outputs_clean,
                tstop=tstop,
                tstep=tstep
            )

            metrics = {
                'max_abs_error': result.max_absolute_error,
                'max_rel_error': result.max_relative_error,
                'rms_error': result.rms_error,
                'correlation': result.correlation,
                'coverage': 100.0 if result.passed else 0.0,
                'validation_mode': mode_desc
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

        mode_desc = "DC sweep (static)"

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
                'coverage': result.coverage_percentage,
                'validation_mode': mode_desc
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

        user_prompt = f"""⚠️  CRITICAL: This code will be compiled with OpenVAF (NOT standard Verilog-AMS).
OpenVAF has LIMITED support. You MUST follow these constraints or the code will FAIL to compile.

=== BANNED FEATURES (Will cause compilation failure) ===
❌ NEVER use `M_PI - Write 3.14159 directly
❌ NEVER use laplace_nd(), laplace_zd(), laplace_zp(), or ANY Laplace function
❌ NEVER use zi_nd(), zi_zd() or ANY zi function
❌ NEVER use $random, white_noise(), flicker_noise()
❌ NEVER use limexp() - use exp() instead

=== ALLOWED FEATURES ===
✅ ddt() for derivatives
✅ idt() for integration
✅ tanh() for saturation
✅ exp(), pow(), sin(), cos(), abs(), min(), max()
✅ Simple arithmetic and if/else

=== How to Model Frequency Response WITHOUT Laplace ===
WRONG: laplace_nd(signal, {{1.0}}, {{tau, 1.0}})
RIGHT: Use ddt() approximation:
  real v_filt;
  analog begin
    v_filt = v_filt + (signal - v_filt) * ddt_timestep / tau;
  end

Or use simple 1st-order with tanh:
  freq_factor = tanh(abs(ddt(signal)) * tau);
  v_out = signal * (1.0 + freq_factor * gain);

Now refine this baseline model to improve accuracy:

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
2. Improve transfer function using ONLY allowed functions (ddt, idt, tanh, exp, pow)
3. Add frequency response if needed, but NO laplace functions
4. Use 3.14159 for pi, NOT `M_PI
5. Output ONLY valid Verilog-AMS code that OpenVAF can compile

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

            # Clean up AI output - extract only the Verilog-AMS module
            # Remove markdown code fences
            if "```" in pass1_va:
                # Extract content between code fences
                lines = pass1_va.split('\n')
                in_fence = False
                code_lines = []
                for line in lines:
                    if line.strip().startswith('```'):
                        in_fence = not in_fence
                        continue
                    if in_fence or (not in_fence and 'module ' in line):
                        code_lines.append(line)
                pass1_va = '\n'.join(code_lines)

            # Find module start and end
            if "module " in pass1_va:
                # Extract from "module" to "endmodule"
                module_start = pass1_va.find("module ")
                if module_start > 0:
                    pass1_va = pass1_va[module_start:]

            if "endmodule" in pass1_va:
                endmodule_pos = pass1_va.rfind("endmodule")
                pass1_va = pass1_va[:endmodule_pos + len("endmodule")]

            # Add back any missing includes at the start
            if "`include" not in pass1_va and "module " in pass1_va:
                module_start = pass1_va.find("module ")
                includes = "`include \"disciplines.vams\"\n\n"
                pass1_va = includes + pass1_va

            # Fix OpenVAF incompatibilities (M_PI, Laplace, etc.)
            pass1_va = fix_openvaf_compatibility(pass1_va)

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

        # Build per-module block_info from baseline VA code
        inputs, outputs = extract_module_ports(baseline_va)
        module_block_info = {
            'name': module_name,
            'inputs': set(f'net:{inp}' for inp in inputs),
            'outputs': set(f'net:{out}' for out in outputs),
            'simulation_axes': set(f'net:{inp}' for inp in inputs),
            'behavior_class': 'NONLINEAR'
        }

        passed, metrics, error_msg = validate_module(
            module_name, pass1_va, spice_netlist, module_block_info, output_dir
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

            correction_prompt = f"""⚠️  CRITICAL: OpenVAF has LIMITED Verilog-AMS support. Your previous code FAILED compilation.

=== COMPILATION FAILED - MUST FIX ===
Error:
{error_msg if error_msg else f"Poor accuracy: max_error={metrics.get('max_abs_error', 'N/A')}, correlation={metrics.get('correlation', 'N/A')}"}

Your Failed Code:
```
{pass1_va}
```

=== BANNED in OpenVAF (causes compilation failure) ===
❌ `M_PI macro - Write 3.14159 directly
❌ laplace_nd(), laplace_zd(), laplace_zp() - NO Laplace functions at all
❌ zi_nd(), zi_zd() - Not supported
❌ $random, white_noise() - Not supported

=== ALLOWED in OpenVAF ===
✅ ddt(), idt(), tanh(), exp(), pow(), abs(), min(), max()

=== How to Fix Laplace Functions ===
If you see: laplace_nd() or laplace_zd()
Replace with: Simple pole approximation
  real v_filtered;
  parameter real tau = 1e-9;
  analog begin
    // Simple RC lowpass filter (1st order)
    ddt(v_filtered) = (signal - v_filtered) / tau;
    output <+ v_filtered;
  end

SPICE Netlist (reference):
```
{netlist_text}
```

Instructions:
1. Remove ALL unsupported functions (`M_PI, laplace, zi, $random)
2. Replace with allowed alternatives (ddt, idt, tanh, exp)
3. Simplify if needed - basic behavioral model is fine
4. Output ONLY corrected Verilog-AMS code

Output corrected module code ONLY. No explanations."""

            try:
                pass3_va = agent.chat(system_prompt, correction_prompt)

                # Clean up AI output - extract only the Verilog-AMS module
                # Remove markdown code fences
                if "```" in pass3_va:
                    lines = pass3_va.split('\n')
                    in_fence = False
                    code_lines = []
                    for line in lines:
                        if line.strip().startswith('```'):
                            in_fence = not in_fence
                            continue
                        if in_fence or (not in_fence and 'module ' in line):
                            code_lines.append(line)
                    pass3_va = '\n'.join(code_lines)

                # Find module start and end
                if "module " in pass3_va:
                    module_start = pass3_va.find("module ")
                    if module_start > 0:
                        pass3_va = pass3_va[module_start:]

                if "endmodule" in pass3_va:
                    endmodule_pos = pass3_va.rfind("endmodule")
                    pass3_va = pass3_va[:endmodule_pos + len("endmodule")]

                # Add back any missing includes
                if "`include" not in pass3_va and "module " in pass3_va:
                    includes = "`include \"disciplines.vams\"\n\n"
                    pass3_va = includes + pass3_va

                # Fix OpenVAF incompatibilities (M_PI, Laplace, etc.)
                pass3_va = fix_openvaf_compatibility(pass3_va)

                # Quick validation of corrected version (reuse module_block_info from Pass 2)
                passed_retry, metrics_retry, error_retry = validate_module(
                    module_name, pass3_va, spice_netlist, module_block_info, output_dir
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
