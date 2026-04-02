#!/usr/bin/env python3
"""
verilog_ams_generator.py

Generates Verilog-AMS code from fitted transfer function models.

Supports:
- Analytic models with smooth blending
- Lookup table (LUT) models
- Multiple inputs/outputs
"""

import numpy as np
from datetime import datetime


class VerilogAMSGenerator:
    """
    Generate Verilog-AMS modules from fitted models
    """

    def __init__(self):
        self.generated_modules = []

    def _sanitize_identifier(self, name):
        """
        Sanitize identifier to ensure it's valid for Verilog-AMS.
        Verilog identifiers must start with letter or underscore, not digit.
        """
        name = name.replace('net:', '').replace(':', '_').replace('v(', '').replace(')', '')
        if name and name[0].isdigit():
            name = 'n' + name
        return name

    def generate_module(self, fitted_model, module_name=None):
        """
        Generate Verilog-AMS module from fitted model

        Args:
            fitted_model: Dict with 'input', 'output', 'model', 'data'
                          - For 1D: input is string
                          - For 2D: input is list [input1, input2]
            module_name: Optional module name (auto-generated if None)

        Returns:
            str: Complete Verilog-AMS module code
        """
        input_name = fitted_model['input']
        output_name = fitted_model['output']
        model = fitted_model['model']

        # Check if this is a 2D model (input is a list) or autonomous (input is None)
        is_2d = isinstance(input_name, list)
        is_autonomous = (input_name is None)

        if module_name is None:
            # Auto-generate name: output_vs_input
            if is_autonomous:
                # Autonomous oscillator - no input
                module_name = f"{output_name}_oscillator"
            elif is_2d:
                input_str = '_'.join(input_name)
                module_name = f"{output_name}_vs_{input_str}"
            else:
                module_name = f"{output_name}_vs_{input_name}"
            # Clean up net: prefix and sanitize for Verilog identifiers
            module_name = module_name.replace('net:', '').replace(':', '_')
            # Ensure module name starts with letter or underscore (not digit)
            # Verilog-AMS identifiers cannot start with digits
            if module_name and module_name[0].isdigit():
                module_name = 'n' + module_name

        if model['model_type'] == 'analytic':
            if is_2d:
                code = self._generate_analytic_2d_module(
                    module_name, input_name, output_name, model, fitted_model['data']
                )
            else:
                code = self._generate_analytic_module(
                    module_name, input_name, output_name, model, fitted_model['data']
                )
        elif model['model_type'] == 'LUT':
            code = self._generate_lut_module(
                module_name, input_name, output_name, model, fitted_model['data']
            )
        elif model['model_type'] == 'LUT_2D':
            code = self._generate_lut_2d_module(
                module_name, input_name, output_name, model, fitted_model['data']
            )
        elif model['model_type'] == 'small_signal':
            code = self._generate_small_signal_module(
                module_name, fitted_model
            )
        elif model['model_type'] == 'linear_ac':
            code = self._generate_linear_ac_module(
                module_name, input_name, output_name, model, fitted_model['data']
            )
        elif model['model_type'] == 'oscillator':
            code = self._generate_oscillator_module(
                module_name, output_name, model, fitted_model['data']
            )
        elif model['model_type'] == 'dynamic':
            code = self._generate_dynamic_module(
                module_name, input_name, output_name, model, fitted_model['data']
            )
        else:
            raise ValueError(f"Unknown model type: {model['model_type']}")

        self.generated_modules.append({
            'name': module_name,
            'code': code
        })

        return code

    def _generate_analytic_module(self, module_name, input_name, output_name, model, data):
        """
        Generate Verilog-AMS for analytic model with smooth blending
        """
        # Extract model details
        inner_model = model['model']
        regions = inner_model.get('regions', [])
        smoothing = inner_model.get('smoothing', {})
        params = inner_model.get('params', {})

        # Get data ranges for validation
        x = data['x']
        y = data['y']
        x_min, x_max = x.min(), x.max()
        y_min, y_max = y.min(), y.max()

        # Clean names (remove net: prefix and sanitize for Verilog)
        input_clean = self._sanitize_identifier(input_name)
        output_clean = self._sanitize_identifier(output_name)

        # Generate header
        code = self._generate_header(module_name, model)

        # Module declaration
        code += f"module {module_name}(\n"
        code += f"    output electrical {output_clean},\n"
        code += f"    input electrical {input_clean}\n"
        code += ");\n\n"

        # Collect all parameters: top-level AND from each region
        all_params = dict(params)
        for region in regions:
            all_params.update(region.get('params', {}))

        # Parameters
        code += "    // Model parameters\n"
        for key, value in all_params.items():
            code += f"    parameter real {key} = {value:.12e};\n"
        code += "\n"

        # Valid range info
        code += f"    // Valid input range (from training data)\n"
        code += f"    parameter real {input_clean}_min = {x_min:.6e};\n"
        code += f"    parameter real {input_clean}_max = {x_max:.6e};\n"
        code += "\n"

        # Analog block
        code += "    analog begin : analog_block\n"

        if smoothing.get('type') == 'tanh_blend':
            code += self._generate_tanh_blended_code(
                input_clean, output_clean, regions, smoothing, params
            )
        else:
            # Fallback to simple piecewise (shouldn't happen)
            code += self._generate_piecewise_code(
                input_clean, output_clean, regions, params
            )

        code += "    end\n"
        code += "endmodule\n"

        return code

    def _generate_tanh_blended_code(self, input_name, output_name, regions, smoothing, params):
        """
        Generate smooth tanh-blended transfer function code
        """
        code = ""
        code += "        real w_active, y_off, y_on, y_out;\n"
        code += "        parameter real output_resistance = 1.0;  // Output resistance (Ohms) for numerical stability\n\n"

        # Smoothing function
        Vth = smoothing['center']
        delta = smoothing['width']

        code += "        // Smooth blending weight (tanh-based)\n"
        code += f"        w_active = 0.5 * (1.0 + tanh((V({input_name}) - {Vth:.12e}) / {delta:.12e}));\n\n"

        # Off region (first region)
        code += "        // Off region (cutoff)\n"
        off_region = regions[0] if len(regions) > 0 else {'expr': '0'}
        code += f"        y_off = {self._translate_expr(off_region['expr'], input_name, params)};\n\n"

        # On region (second region)
        code += "        // On region (active)\n"
        on_region = regions[1] if len(regions) > 1 else {'expr': '0'}
        code += f"        y_on = {self._translate_expr(on_region['expr'], input_name, params)};\n\n"

        # Blended output
        code += "        // Smooth blend between regions\n"
        code += "        y_out = (1.0 - w_active) * y_off + w_active * y_on;\n\n"

        code += "        // Use current source with output resistance (Thevenin equivalent)\n"
        code += f"        I({output_name}) <+ (y_out - V({output_name})) / output_resistance;\n"

        return code

    def _generate_piecewise_code(self, input_name, output_name, regions, params):
        """
        Generate hard piecewise code (fallback)
        """
        code = ""
        code += "        real y_out;\n"
        code += "        parameter real output_resistance = 1.0;  // Output resistance (Ohms) for numerical stability\n\n"

        for i, region in enumerate(regions):
            if i == 0:
                code += "        if "
            else:
                code += "        else if "

            # Parse range condition
            range_str = region.get('range', 'all')
            if '<<' in range_str:
                threshold = range_str.split('<<')[1].strip()
                code += f"(V({input_name}) < {threshold})\n"
            elif '>>' in range_str:
                threshold = range_str.split('>>')[1].strip()
                code += f"(V({input_name}) > {threshold})\n"
            else:
                code += "(1)  // default\n"

            # Merge top-level params with region-level params for expression translation
            region_params = dict(params)
            region_params.update(region.get('params', {}))
            expr = self._translate_expr(region['expr'], input_name, region_params)
            code += f"            y_out = {expr};\n"

        code += "\n        // Use current source with output resistance (Thevenin equivalent)\n"
        code += f"        I({output_name}) <+ (y_out - V({output_name})) / output_resistance;\n"

        return code

    def _translate_expr(self, expr, input_name, params):
        """
        Translate mathematical expression to Verilog-AMS

        Converts Python math expressions to Verilog-AMS:
        - x → V(input_name)
        - expr**N → pow(expr, N)
        - Threshold expressions wrapped in max(..., 0)
        """
        verilog_expr = expr

        # Replace 'x' with V(input_name)
        verilog_expr = verilog_expr.replace('x', f'V({input_name})')

        # Handle **2 pattern (quadratic expressions)
        if '**2' in verilog_expr:
            idx = verilog_expr.index('**2')

            # Find matching parentheses backwards from **2
            # The character before **2 should be ')'
            if idx > 0 and verilog_expr[idx-1] == ')':
                paren_depth = 1  # Start at 1 since we know there's a ')'
                start = -1

                for i in range(idx - 2, -1, -1):  # Start from idx-2 (before the ')')
                    char = verilog_expr[i]

                    if char == ')':
                        paren_depth += 1
                    elif char == '(':
                        paren_depth -= 1

                        if paren_depth == 0:
                            start = i
                            break

                if start >= 0:
                    # Extract base expression (between matching parens)
                    base_expr = verilog_expr[start+1:idx-1]  # idx-1 is the ')'
                    prefix = verilog_expr[:start]

                    # Wrap in max if threshold subtraction
                    if 'Vth' in base_expr and '-' in base_expr:
                        verilog_expr = f'{prefix}pow(max({base_expr}, 0.0), 2)'
                    else:
                        verilog_expr = f'{prefix}pow({base_expr}, 2)'

        return verilog_expr

    def _generate_lut_module(self, module_name, input_name, output_name, model, data):
        """
        Generate Verilog-AMS for lookup table model
        """
        x = data['x']
        y = data['y']

        input_clean = self._sanitize_identifier(input_name)
        output_clean = self._sanitize_identifier(output_name)

        # Generate header
        code = self._generate_header(module_name, model)

        # Module declaration
        code += f"module {module_name}(\n"
        code += f"    output electrical {output_clean},\n"
        code += f"    input electrical {input_clean}\n"
        code += ");\n\n"

        # Generate table file reference
        table_file = f"{module_name}_lut.tbl"

        code += f"    // Lookup table parameters\n"
        code += f"    parameter real x_min = {x.min():.12e};\n"
        code += f"    parameter real x_max = {x.max():.12e};\n"
        code += f"    parameter integer n_points = {len(x)};\n"
        code += "\n"

        code += "    analog begin : analog_block\n"
        code += "        real y_out;\n\n"

        code += "        // Linear interpolation lookup table\n"
        code += f"        // Table data stored in external file: {table_file}\n"
        code += "        // Format: input_value output_value (one pair per line)\n"
        code += f"        // For now, using $table_model would require external file\n\n"

        code += "        // Simple linear interpolation implementation\n"
        code += "        // (For production, use $table_model with external .tbl file)\n"

        # For simplicity, generate inline piecewise linear approximation
        code += self._generate_inline_lut(input_clean, output_clean, x, y)

        code += "    end\n"
        code += "endmodule\n"

        # Also generate the .tbl file content
        table_content = self._generate_table_file(x, y)
        self.generated_modules.append({
            'name': f"{module_name}_lut.tbl",
            'code': table_content,
            'is_table': True
        })

        return code

    def _generate_inline_lut(self, input_name, output_name, x, y):
        """
        Generate inline piecewise linear interpolation
        """
        code = ""
        code += "        parameter real output_resistance = 1.0;  // Output resistance (Ohms) for numerical stability\n\n"

        # Generate piecewise linear segments
        n_segments = min(10, len(x) - 1)  # Limit to 10 segments for readability
        indices = np.linspace(0, len(x) - 1, n_segments + 1, dtype=int)

        for i in range(len(indices) - 1):
            idx0 = indices[i]
            idx1 = indices[i + 1]

            x0, x1 = x[idx0], x[idx1]
            y0, y1 = y[idx0], y[idx1]

            if i == 0:
                code += f"        if (V({input_name}) <= {x1:.12e})\n"
            elif i == len(indices) - 2:
                code += f"        else\n"
            else:
                code += f"        else if (V({input_name}) <= {x1:.12e})\n"

            # Linear interpolation
            slope = (y1 - y0) / (x1 - x0) if abs(x1 - x0) > 1e-15 else 0
            code += f"            y_out = {y0:.12e} + {slope:.12e} * (V({input_name}) - {x0:.12e});\n"

        code += "\n        // Use current source with output resistance (Thevenin equivalent)\n"
        code += f"        I({output_name}) <+ (y_out - V({output_name})) / output_resistance;\n"

        return code

    def _generate_table_file(self, x, y):
        """
        Generate .tbl file content for $table_model
        """
        content = "# Lookup table for Verilog-AMS $table_model\n"
        content += "# Format: input_value output_value\n"
        content += f"# Generated: {datetime.now().isoformat()}\n"
        content += f"# Points: {len(x)}\n\n"

        for xi, yi in zip(x, y):
            content += f"{xi:.12e}  {yi:.12e}\n"

        return content

    def _generate_linear_ac_module(self, module_name, input_name, output_name, model, data):
        """
        Generate Verilog-AMS for linear AC frequency response model

        For structurally linear circuits (passive RLC), generates a simple
        linear gain model based on DC gain.

        Args:
            module_name: Module name
            input_name: Input node name
            output_name: Output node name
            model: Model dict with DC gain and frequency response
            data: Data dict with frequency, magnitude, phase arrays

        Returns:
            str: Verilog-AMS code
        """
        input_clean = self._sanitize_identifier(input_name)
        output_clean = self._sanitize_identifier(output_name)

        dc_gain = model.get('dc_gain', 1.0)

        # Generate header
        code = self._generate_header(module_name, model)

        # Module declaration
        code += f"module {module_name}(\n"
        code += f"    output electrical {output_clean},\n"
        code += f"    input electrical {input_clean}\n"
        code += ");\n\n"

        # Parameters
        code += "    // Linear transfer function parameters\n"
        code += f"    parameter real dc_gain = {dc_gain:.12e};\n"
        code += "    parameter real output_resistance = 1.0;  // Output resistance (Ohms) for numerical stability\n"
        code += "\n"

        # For now, generate simple resistive divider / linear gain
        # TODO: Could add pole/zero fitting here for more accurate frequency response
        code += "    analog begin : analog_block\n"
        code += "        real v_ideal;\n\n"
        code += f"        // Linear DC transfer: {output_clean} = dc_gain * {input_clean}\n"
        code += f"        v_ideal = dc_gain * V({input_clean});\n"
        code += "        // Use current source with output resistance (Thevenin equivalent)\n"
        code += f"        I({output_clean}) <+ (v_ideal - V({output_clean})) / output_resistance;\n"
        code += "    end\n"
        code += "endmodule\n"

        return code

    def _generate_oscillator_module(self, module_name, output_name, model, data):
        """
        Generate Verilog-AMS for oscillator model

        Oscillators are self-sustaining circuits that generate time-varying
        signals without external input. Characterized by:
        - Frequency (Hz)
        - Amplitude (peak-to-peak volts)
        - DC offset (volts)
        - Waveform type (sine, square, triangle)

        Supports two API styles:
        - Nested params: model['params']['frequency'], model['waveform']
        - Direct access: model['frequency'], model['waveform_type']

        Args:
            module_name: Module name
            output_name: Output node name
            model: Model dict with oscillator parameters
            data: Optional data dict with characterization info

        Returns:
            str: Verilog-AMS code
        """
        output_clean = self._sanitize_identifier(output_name)

        # Handle both API styles for backward compatibility
        params = model.get('params', {})

        if params:
            # Nested params style (from transient extraction fallback)
            frequency = params.get('frequency', 1e6)
            amplitude = params.get('amplitude', 1.0)
            dc_offset = params.get('offset', params.get('dc_offset', 0.0))
            duty_cycle = params.get('duty_cycle', 0.5)
            waveform_type = model.get('waveform', model.get('waveform_type', 'sine'))
        else:
            # Direct access style (legacy)
            frequency = model.get('frequency', 1e6)  # Default: 1 MHz
            amplitude = model.get('amplitude', 1.0)  # Peak-to-peak amplitude
            dc_offset = model.get('dc_offset', 0.0)
            waveform_type = model.get('waveform_type', 'sine')
            duty_cycle = 0.5

        # Generate header
        code = self._generate_header(module_name, model)

        # Module declaration - oscillators have no inputs, only output
        code += f"module {module_name}(\n"
        code += f"    output electrical {output_clean}\n"
        code += ");\n\n"

        # Parameters
        code += "    // Oscillator parameters\n"
        code += f"    parameter real frequency = {frequency:.12e};  // Hz\n"
        code += f"    parameter real amplitude = {amplitude:.12e};  // Peak-to-peak (V)\n"
        code += f"    parameter real dc_offset = {dc_offset:.12e};  // DC offset (V)\n"

        if waveform_type == 'square':
            code += f"    parameter real duty_cycle = {duty_cycle:.6f};  // 0-1\n"

        code += "    parameter real output_resistance = 1.0;  // Output resistance (Ohms) for numerical stability\n"
        code += "\n"

        # Analog block
        code += "    analog begin : analog_block\n"
        code += "        real omega, phase, signal, v_ideal;\n\n"

        code += "        // Angular frequency (rad/s)\n"
        code += "        omega = 2.0 * `M_PI * frequency;\n\n"

        code += "        // Phase (accumulated from time)\n"
        code += "        phase = omega * $abstime;\n\n"

        code += "        // Generate waveform\n"

        # Generate waveform based on type
        if waveform_type == 'sine':
            code += "        signal = amplitude * sin(phase);\n\n"

        elif waveform_type == 'square':
            code += "        // Square wave using transition function for smoothness\n"
            code += "        if (phase - floor(phase/(2*`M_PI))*(2*`M_PI) < 2*`M_PI*duty_cycle)\n"
            code += "            signal = amplitude;\n"
            code += "        else\n"
            code += "            signal = -amplitude;\n\n"

        elif waveform_type == 'triangle':
            code += "        // Triangle wave\n"
            code += "        signal = (4*amplitude/`M_PI) * asin(sin(phase));\n\n"

        elif waveform_type == 'complex':
            # Default to sine wave for complex waveforms
            code += "        // Complex waveform approximated as sine\n"
            code += "        signal = amplitude * sin(phase);\n\n"

        else:  # Default to sine
            code += "        // Default sinusoidal oscillation\n"
            code += "        signal = amplitude * sin(phase);\n\n"

        # Apply DC offset
        code += "        // Drive output with Thevenin equivalent\n"
        code += "        v_ideal = dc_offset + signal;\n"
        code += f"        I({output_clean}) <+ (v_ideal - V({output_clean})) / output_resistance;\n"

        code += "    end\n"
        code += "endmodule\n"

        return code

    def _generate_small_signal_module(self, module_name, fitted_model):
        """
        Generate Verilog-AMS for small-signal linear model

        Args:
            module_name: Module name
            fitted_model: Dict with small-signal model info

        Returns:
            str: Verilog-AMS code
        """
        model = fitted_model['model']
        params = model.get('parameters', {})
        equations = model.get('equations', [])

        # Parse terminal names from fitted_model
        # Expected structure: fitted_model has 'terminals' dict
        # e.g., {'vgs': ('vg', 'vs'), 'vds': ('vd', 'vs'), 'vbs': ('vb', 'vs'), 'id': ('vd', 'vs')}
        terminals = fitted_model.get('terminals', {})

        # Generate header
        code = self._generate_header(module_name, model)

        # Module declaration with terminals
        # Small-signal model for MOSFET: 4-terminal device
        code += f"module {module_name}(\n"
        code += "    inout electrical vd,  // drain\n"
        code += "    inout electrical vg,  // gate\n"
        code += "    inout electrical vs,  // source\n"
        code += "    inout electrical vb   // bulk\n"
        code += ");\n\n"

        # Parameters
        code += "    // Small-signal parameters (linearized at DC operating point)\n"
        for key, value in params.items():
            code += f"    parameter real {key} = {value:.12e};\n"
        code += "\n"

        # Analog block
        code += "    analog begin : analog_block\n"

        # Generate small-signal equations
        # Standard MOSFET small-signal: id = gm*vgs + gds*vds + gmb*vbs
        gm = params.get('gm', 0.0)
        gds = params.get('gds', 0.0)
        gmb = params.get('gmb', 0.0)

        # Use direct inline expressions to avoid intermediate variable issues
        # This makes the model easier for equivalence checkers to evaluate
        code += "        // Small-signal drain current: id = gm*vgs + gds*vds + gmb*vbs\n"
        code += "        I(vd, vs) <+ gm*V(vg, vs) + gds*V(vd, vs)"
        if gmb != 0.0:
            code += " + gmb*V(vb, vs)"
        code += ";\n"

        code += "    end\n"
        code += "endmodule\n"

        return code


    def _generate_dynamic_module(self, module_name, input_name, output_name, model, data):
        """
        Generate Verilog-AMS for dynamic model (combines DC + transient)

        Dynamic models have:
        - DC gain from DC sweep
        - Bandwidth/time constant from transient

        If input_name is None, generates an autonomous oscillator (no inputs).
        If input_name is a list, generates a multi-input module.
        """
        header = self._generate_header(module_name, model)

        # Extract parameters
        params = model.get('combined_params', {})
        dc_gain = params.get('dc_gain', 1.0)
        bandwidth = params.get('bandwidth')
        time_constant = params.get('time_constant')
        model_class = params.get('model_class', 'dc_only')

        # Clean output name
        output_clean = self._sanitize_identifier(output_name).replace('v(', '').replace(')', '')

        # Handle different input cases
        if input_name is None:
            # Autonomous oscillator (no inputs)
            # Generate as oscillator model instead
            # Update model type for correct header generation
            oscillator_model = model.copy()
            oscillator_model['model_type'] = 'oscillator'
            return self._generate_oscillator_module(module_name, output_name, oscillator_model, data)

        elif isinstance(input_name, list):
            # Multi-input model
            input_clean_list = [self._sanitize_identifier(inp) for inp in input_name]
            inputs_decl = ',\n  '.join([f"input electrical {inp}" for inp in input_clean_list])

            # For multi-input, use first input for now (simplified model)
            # TODO: Implement proper multi-input transfer function
            input_clean = input_clean_list[0]
        else:
            # Single input
            input_clean = self._sanitize_identifier(input_name).replace('v(', '').replace(')', '')
            inputs_decl = f"input electrical {input_clean}"

        # Generate module
        code = header + f"""module {module_name} (
  {inputs_decl},
  output electrical {output_clean}
);

  // Dynamic model parameters
  parameter real dc_gain = {dc_gain};"""

        if bandwidth is not None and time_constant is not None:
            code += f"""
  parameter real bandwidth = {bandwidth};  // Hz
  parameter real time_constant = {time_constant};  // seconds"""

        code += """
  parameter real output_resistance = 1.0;  // Output resistance (Ohms) for numerical stability
"""

        if bandwidth is not None and time_constant is not None:
            code += f"""
  // Model class: {model_class}
  // Transfer function: H(s) = {dc_gain:.3e} / (1 + s*{time_constant:.3e})
"""
        else:
            code += f"""
  // Model class: {model_class} (DC-only, no dynamics available)
"""

        code += f"""
  real v_ideal;

  analog begin
    // Simple DC gain model with Thevenin equivalent
    v_ideal = dc_gain * V({input_clean});
    I({output_clean}) <+ (v_ideal - V({output_clean})) / output_resistance;
  end

endmodule
"""

        return code

    def _generate_header(self, module_name, model):
        """
        Generate file header with metadata
        """
        header = f"""// Verilog-AMS Behavioral Model
// Generated by circuit_preprocess pipeline
// Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
//
// Module: {module_name}
// Model type: {model['model_type']}
// Intent: {model.get('intent', 'unknown')}
"""

        if model['model_type'] == 'analytic':
            header += f"// Fit quality (NRMSE): {model.get('nrmse', 'N/A')}\n"
        elif model['model_type'] == 'oscillator':
            header += f"// Oscillator frequency: {model.get('params', {}).get('frequency', 'N/A')} Hz\n"
            header += f"// Waveform type: {model.get('waveform', 'unknown')}\n"
        elif model['model_type'] == 'dynamic':
            params = model.get('combined_params', {})
            if params.get('dc_gain') is not None:
                header += f"// DC gain: {params['dc_gain']:.3e}\n"
            if params.get('bandwidth') is not None:
                header += f"// Bandwidth: {params['bandwidth']:.3e} Hz\n"
            if params.get('time_constant') is not None:
                header += f"// Time constant: {params['time_constant']:.3e} s\n"

        header += "\n`include \"disciplines.vams\"\n"

        # Add constants.vams if the model uses M_PI or M_TWO_PI
        # (oscillator models use these constants)
        if model.get('model_type') == 'oscillator':
            header += "`include \"constants.vams\"\n"

        header += "\n"

        return header

    def save_module(self, module_info, output_dir='.'):
        """
        Save generated module to file

        Args:
            module_info: Dict with 'name' and 'code'
            output_dir: Directory to save files
        """
        from pathlib import Path

        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        is_table = module_info.get('is_table', False)
        filename = module_info['name']

        if not is_table and not filename.endswith('.va'):
            filename = filename + '.va'

        file_path = output_path / filename

        with open(file_path, 'w') as f:
            f.write(module_info['code'])

        return file_path

    def save_all(self, output_dir='.'):
        """
        Save all generated modules

        Returns:
            list: Paths to saved files
        """
        saved_files = []

        for module_info in self.generated_modules:
            file_path = self.save_module(module_info, output_dir)
            saved_files.append(file_path)

        return saved_files

    def _generate_analytic_2d_module(self, module_name, input_names, output_name, model, data):
        """
        Generate Verilog-AMS for 2D analytic model z = f(x1, x2)
        """
        input1 = input_names[0].replace('net:', '')
        input2 = input_names[1].replace('net:', '')
        output_clean = self._sanitize_identifier(output_name)

        inner_model = model['model']
        model_type = inner_model['type']
        params = inner_model['params']

        # Generate header
        code = self._generate_header(module_name, model)

        # Module declaration
        code += f"module {module_name}(\n"
        code += f"    output electrical {output_clean},\n"
        code += f"    input electrical {input1},\n"
        code += f"    input electrical {input2}\n"
        code += ");\n\n"

        # Parameters
        code += "    // Model parameters\n"
        code += "    parameter real output_resistance = 1.0;  // Output resistance (Ohms) for numerical stability\n\n"

        # Generate equation based on model type
        code += "    analog begin : analog_block\n"
        code += "        real v_ideal;\n\n"

        if model_type == 'differential':
            a = params['a']
            b = params['b']
            c = params['c']
            code += f"        // Differential model: z = a + b*(x1-x2) + c*(x1-x2)^2\n"
            code += f"        v_ideal = {a:.12e} + {b:.12e}*(V({input1}) - V({input2})) + {c:.12e}*pow(V({input1}) - V({input2}), 2);\n"

        elif model_type == 'differential_squared':
            a = params['a']
            b = params['b']
            c = params['c']
            code += f"        // Differential squared model: z = a + b*(x1-x2)^2 + c*(x1-x2)^3\n"
            code += f"        v_ideal = {a:.12e} + {b:.12e}*pow(V({input1}) - V({input2}), 2) + {c:.12e}*pow(V({input1}) - V({input2}), 3);\n"

        elif model_type == 'bilinear':
            a = params['a']
            b = params['b']
            c = params['c']
            d = params['d']
            code += f"        // Bilinear model: z = a + b*x1 + c*x2 + d*x1*x2\n"
            code += f"        v_ideal = {a:.12e} + {b:.12e}*V({input1}) + {c:.12e}*V({input2}) + {d:.12e}*V({input1})*V({input2});\n"

        elif model_type == 'quadratic':
            a = params['a']
            b = params['b']
            c = params['c']
            d = params['d']
            e = params['e']
            f = params['f']
            code += f"        // Quadratic model: z = a + b*x1 + c*x2 + d*x1^2 + e*x2^2 + f*x1*x2\n"
            code += f"        v_ideal = {a:.12e} + {b:.12e}*V({input1}) + {c:.12e}*V({input2}) + {d:.12e}*pow(V({input1}), 2) + {e:.12e}*pow(V({input2}), 2) + {f:.12e}*V({input1})*V({input2});\n"

        code += "\n        // Use current source with output resistance (Thevenin equivalent)\n"
        code += f"        I({output_clean}) <+ (v_ideal - V({output_clean})) / output_resistance;\n"

        code += "    end\n"
        code += "endmodule\n"

        return code

    def _generate_lut_2d_module(self, module_name, input_names, output_name, model, data):
        """
        Generate Verilog-AMS for 2D lookup table z = LUT(x1, x2)
        Implements bilinear interpolation with embedded table data
        """
        input1 = input_names[0].replace('net:', '')
        input2 = input_names[1].replace('net:', '')
        output_clean = self._sanitize_identifier(output_name)

        x1 = data['x1']
        x2 = data['x2']
        z = data['z']

        n1 = len(x1)
        n2 = len(x2)

        # Generate header
        code = self._generate_header(module_name, model)

        # Module declaration
        code += f"module {module_name}(\n"
        code += f"    output electrical {output_clean},\n"
        code += f"    input electrical {input1},\n"
        code += f"    input electrical {input2}\n"
        code += ");\n\n"

        # Table parameters
        code += f"    // 2D Lookup table parameters\n"
        code += f"    parameter real x1_min = {x1.min():.12e};\n"
        code += f"    parameter real x1_max = {x1.max():.12e};\n"
        code += f"    parameter integer n1 = {n1};\n"
        code += f"    parameter real x2_min = {x2.min():.12e};\n"
        code += f"    parameter real x2_max = {x2.max():.12e};\n"
        code += f"    parameter integer n2 = {n2};\n"
        code += "    parameter real output_resistance = 1.0;  // Output resistance (Ohms) for numerical stability\n"
        code += "\n"

        # Since OpenVAF doesn't support arrays, embed table as individual parameters
        code += f"    // Embedded lookup table data as individual parameters ({n1}×{n2} grid)\n"

        # Flatten z in row-major order and create individual parameters
        flat_z = z.ravel()
        for i in range(len(flat_z)):
            code += f"    parameter real lut_{i} = {flat_z[i]:.12e};\n"
        code += "\n"

        # Analog block with bilinear interpolation
        code += "    analog begin : analog_block\n"
        code += "        real v_ideal;\n"
        code += "        real v1, v2;\n"
        code += "        real i1_real, i2_real;\n"
        code += "        integer i1, i2, i1p, i2p;\n"
        code += "        integer idx00, idx01, idx10, idx11;\n"
        code += "        real w1, w2;\n"
        code += "        real z00, z01, z10, z11;\n"
        code += "        real z0, z1;\n\n"

        code += "        // Read input voltages\n"
        code += f"        v1 = V({input1});\n"
        code += f"        v2 = V({input2});\n\n"

        code += "        // Clamp to table bounds\n"
        code += "        if (v1 < x1_min) v1 = x1_min;\n"
        code += "        if (v1 > x1_max) v1 = x1_max;\n"
        code += "        if (v2 < x2_min) v2 = x2_min;\n"
        code += "        if (v2 > x2_max) v2 = x2_max;\n\n"

        code += "        // Compute continuous indices (with guards for constant axes)\n"
        code += "        if (abs(x1_max - x1_min) < 1e-12)\n"
        code += "            i1_real = 0.0;  // Constant axis\n"
        code += "        else\n"
        code += "            i1_real = (v1 - x1_min) * (n1 - 1) / (x1_max - x1_min);\n\n"
        code += "        if (abs(x2_max - x2_min) < 1e-12)\n"
        code += "            i2_real = 0.0;  // Constant axis\n"
        code += "        else\n"
        code += "            i2_real = (v2 - x2_min) * (n2 - 1) / (x2_max - x2_min);\n\n"

        code += "        // Integer indices (floor)\n"
        code += "        i1 = $floor(i1_real);\n"
        code += "        i2 = $floor(i2_real);\n\n"

        code += "        // Ensure indices stay in bounds\n"
        code += "        if (i1 < 0) i1 = 0;\n"
        code += "        if (i1 >= n1 - 1) i1 = n1 - 2;\n"
        code += "        if (i2 < 0) i2 = 0;\n"
        code += "        if (i2 >= n2 - 1) i2 = n2 - 2;\n\n"

        code += "        i1p = i1 + 1;\n"
        code += "        i2p = i2 + 1;\n\n"

        code += "        // Interpolation weights\n"
        code += "        w1 = i1_real - i1;\n"
        code += "        w2 = i2_real - i2;\n\n"

        code += "        // Compute flat indices (row-major)\n"
        code += "        idx00 = i1 * n2 + i2;\n"
        code += "        idx01 = i1 * n2 + i2p;\n"
        code += "        idx10 = i1p * n2 + i2;\n"
        code += "        idx11 = i1p * n2 + i2p;\n\n"

        # Generate lookup function using case statement
        code += "        // Lookup corner values using case statement\n"
        code += "        case (idx00)\n"
        for i in range(len(flat_z)):
            code += f"            {i}: z00 = lut_{i};\n"
        code += f"            default: z00 = lut_0;\n"
        code += "        endcase\n\n"

        code += "        case (idx01)\n"
        for i in range(len(flat_z)):
            code += f"            {i}: z01 = lut_{i};\n"
        code += f"            default: z01 = lut_0;\n"
        code += "        endcase\n\n"

        code += "        case (idx10)\n"
        for i in range(len(flat_z)):
            code += f"            {i}: z10 = lut_{i};\n"
        code += f"            default: z10 = lut_0;\n"
        code += "        endcase\n\n"

        code += "        case (idx11)\n"
        for i in range(len(flat_z)):
            code += f"            {i}: z11 = lut_{i};\n"
        code += f"            default: z11 = lut_0;\n"
        code += "        endcase\n\n"

        code += "        // Bilinear interpolation\n"
        code += "        z0 = z00 * (1.0 - w2) + z01 * w2;\n"
        code += "        z1 = z10 * (1.0 - w2) + z11 * w2;\n"
        code += "        v_ideal = z0 * (1.0 - w1) + z1 * w1;\n\n"

        code += "        // Use current source with output resistance (Thevenin equivalent)\n"
        code += f"        I({output_clean}) <+ (v_ideal - V({output_clean})) / output_resistance;\n"

        code += "    end\n"
        code += "endmodule\n"

        # Also generate the .tbl file with 2D data
        table_content = self._generate_table_file_2d(x1, x2, z)
        self.generated_modules.append({
            'name': f"{module_name}_lut2d.tbl",
            'code': table_content,
            'is_table': True
        })

        return code

    def _generate_table_file_2d(self, x1, x2, z):
        """
        Generate 2D table file content
        Format: x1 x2 z (one row per grid point)
        """
        content = f"# 2D Lookup Table\n"
        content += f"# Format: x1 x2 z\n"
        content += f"# Grid: {len(x1)} × {len(x2)}\n\n"

        for i in range(len(x1)):
            for j in range(len(x2)):
                content += f"{x1[i]:.12e}\t{x2[j]:.12e}\t{z[i,j]:.12e}\n"

        return content


# ============================================================
# Convenience functions
# ============================================================

def generate_verilog_ams(fitted_models, output_dir='.'):
    """
    Generate Verilog-AMS modules from fitted models

    Args:
        fitted_models: List of fitted model dicts from pipeline
        output_dir: Directory to save .va files

    Returns:
        list: Paths to generated files
    """
    generator = VerilogAMSGenerator()

    for fitted_model in fitted_models:
        code = generator.generate_module(fitted_model)
        print(f"Generated module for {fitted_model['output']} = f({fitted_model['input']})")

    saved_files = generator.save_all(output_dir)

    print(f"\nSaved {len(saved_files)} files to {output_dir}/")
    for f in saved_files:
        print(f"  - {f.name}")

    return saved_files

# ============================================================
# Example usage
# ============================================================

if __name__ == "__main__":
    # Test with synthetic data
    import numpy as np
    from pipeline_ext.fit_transfer_function import fit_transfer_function

    # Create test data
    x = np.linspace(0, 1.5, 50)
    y = np.where(x > 0.4, 4.2e-5 * (x - 0.4)**2, 0)

    # Fit model
    model = fit_transfer_function(x, y)

    # Create fitted model structure
    fitted_model = {
        'input': 'vin',
        'output': 'vout',
        'model': model,
        'data': {'x': x, 'y': y}
    }

    # Generate Verilog-AMS
    generator = VerilogAMSGenerator()
    code = generator.generate_module(fitted_model, 'test_transfer_function')

    print("="*60)
    print("GENERATED VERILOG-AMS CODE:")
    print("="*60)
    print(code)

    # Save to file
    saved = generator.save_all('/tmp')
    print(f"\nSaved to: {saved}")
