# pipeline_ext — advanced programmatic pipeline components
#
# Adapted from vrajesh_sandbox's pipeline/ package.
# Named pipeline_ext to avoid shadowing the top-level pipeline.py module.
#
# Key modules:
#   circuit_analyzer          — bipartite graph analysis, block extraction
#   fit_transfer_function     — 1D/2D numeric model fitting (analytic or LUT)
#   verilog_ams_generator     — template-based Verilog-AMS code generation
#   simulation_planner        — sweep range / independence detection planner
#   extract_small_signal_model— gm/gds/gmb extraction from DC op-point
#   complete_pipeline         — 8-step programmatic orchestrator
