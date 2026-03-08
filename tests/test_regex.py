#!/usr/bin/env python3
import re

expr = "k*(V(vin) - Vth)**2"

pattern = r'\(([^)]+)\)\*\*(\d+)'

matches = re.findall(pattern, expr)
print(f"Expression: {expr}")
print(f"Pattern: {pattern}")
print(f"Matches: {matches}")

# Try substitution
def convert_power(match):
    base = match.group(1)
    exp = match.group(2)
    print(f"  Base: '{base}', Exp: '{exp}'")
    return f'pow(max({base}, 0.0), {exp})'

result = re.sub(pattern, convert_power, expr)
print(f"Result: {result}")
