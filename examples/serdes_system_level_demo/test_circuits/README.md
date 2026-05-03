# Test Circuits

This directory contains all the test circuits used during development and debugging of the SerDes system-level model generation pipeline.

## Test Circuit Categories

### SPICE Reference Testing
- `verify_spice_reference.cir` - Verify SPICE netlist produces varying output
- `test_fixed_netlist.cir` - Test with fixed AC coupling
- `test_transient_only.cir` - Transient-only simulation

### Signal Chain Debugging
- `debug_signal_chain.cir` - Probe all intermediate nodes
- `test_signal_chain.cir` - Simplified signal chain test
- `test_ctle_inputs.cir` - Check CTLE input signals
- `test_saved_nodes.cir` - Save all key node voltages
- `test_final_output.cir` - Test final output only

### OSDI Model Testing
- `test_final_model.cir` - Test compiled OSDI model
- `test_osdi_load.cir` - Test OSDI loading
- `test_osdi_dc_sweep.cir` - DC sweep with OSDI

### DC Sweep Testing
- `test_dc_sweep.cir` - Basic DC sweep
- `test_2d_sweep.cir` - 2D parameter sweep
- `test_serdes_2d.cir` - SerDes-specific 2D sweep
- `test_flattened_sweep.cir` - Sweep on flattened netlist

### Component Testing
- `test_opamp_sweep.cir` - Op-amp characterization
- `test_bad_node.cir` - Test with intentional errors
- `test_list_nodes.cir` - List all available nodes

### Utilities
- `test_runner.cir` - Automated test runner
- `test_runner_fixed.cir` - Fixed version of test runner
- `test_vectors.cir` - Test vector generation
- `test_preload.cir` - OSDI pre-loading test

## Usage

Run any test circuit with ngspice:
```bash
ngspice -b <circuit_name>.cir
```

View results:
```bash
ngspice -b <circuit_name>.cir -o output.log
cat output.log
```
