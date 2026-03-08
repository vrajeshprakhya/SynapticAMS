#!/usr/bin/env python3

expr = "k*(x - Vth)**2"
input_name = "vin"

# Step 1: Replace x
verilog_expr = expr.replace('x', f'V({input_name})')
print(f"After x replacement: {verilog_expr}")

# Step 2: Find **2
if '**2' in verilog_expr:
    idx = verilog_expr.index('**2')
    print(f"Found **2 at index {idx}")

    paren_depth = 0
    start = -1

    for i in range(idx - 1, -1, -1):
        char = verilog_expr[i]

        if char == ')':
            paren_depth += 1
        elif char == '(':
            paren_depth -= 1

            if paren_depth < 0:
                start = i
                print(f"Found matching ( at index {i}")
                break

        print(f"  i={i}, char='{char}', depth={paren_depth}")

    if start >= 0:
        base_expr = verilog_expr[start+1:idx]
        prefix = verilog_expr[:start]
        print(f"\nBase expression: '{base_expr}'")
        print(f"Prefix: '{prefix}'")

        if 'Vth' in base_expr and '-' in base_expr:
            result = f'{prefix}pow(max({base_expr}, 0.0), 2)'
        else:
            result = f'{prefix}pow({base_expr}, 2)'

        print(f"\nResult: {result}")
    else:
        print("ERROR: No matching paren found")
