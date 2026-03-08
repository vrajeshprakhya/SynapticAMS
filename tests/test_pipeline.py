#!/usr/bin/env python3
"""
Test pipeline with a proper circuit that has behavioral transfer function
"""

from pipeline_example import run_pipeline

# Better test circuit: NMOS with resistor load (common source amplifier)
test_netlist_cs_amp = """
* Common source amplifier
M1 vout vin 0 0 NMOS W=10u L=1u
RD vdd vout 10k
VDD vdd 0 DC 1.8V
Vin vin 0 DC 0V
.model NMOS NMOS (LEVEL=1 VTO=0.4 KP=100u LAMBDA=0.02)
"""

print("Testing with common source amplifier")
print("=" * 60)
print(test_netlist_cs_amp)
print("=" * 60)

models = run_pipeline(test_netlist_cs_amp)

if models:
    print("\n" + "=" * 60)
    print("SUCCESS! Models fitted:")
    print("=" * 60)
    for model in models:
        print(f"\n{model['output']} = f({model['input']})")
        print(f"  Model type: {model['model']['model_type']}")
        print(f"  Intent: {model['model']['intent']}")
else:
    print("\nNo models fitted - check circuit or debug pipeline")
